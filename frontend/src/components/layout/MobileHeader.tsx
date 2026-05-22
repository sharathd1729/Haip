"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Bell, ChevronRight } from "lucide-react";
import { useBrandTheme } from "@/components/providers/BrandThemeProvider";

const ROUTE_LABELS: Record<string, string> = {
  dashboard:    "Dashboard",
  inbox:        "Inbox",
  calls:        "Calls",
  inquiries:    "Inquiries",
  guests:       "Guests",
  properties:   "Properties",
  analytics:    "Analytics",
  reports:      "Reports",
  qa:           "QA Scores",
  compliance:   "Compliance",
  settings:     "Settings",
  integrations: "Integrations",
  team:         "Team",
  branding:     "Branding",
  billing:      "Billing",
  profile:      "Profile",
  help:         "Help",
  messaging:    "Messaging",
  templates:    "Templates",
  campaigns:    "Campaigns",
  subscribers:  "Subscribers",
  flows:        "Flow Builder",
};

function PageTitle() {
  const pathname = usePathname();
  const segments = pathname.split("/").filter(Boolean);
  const last = segments[segments.length - 1] ?? "dashboard";
  return (
    <span className="font-semibold text-white/85 text-sm">
      {ROUTE_LABELS[last] ?? last.charAt(0).toUpperCase() + last.slice(1)}
    </span>
  );
}

interface MobileHeaderProps {
  user?: { name?: string | null; email?: string | null; role?: string };
}

export function MobileHeader({ user }: MobileHeaderProps) {
  const [bellOpen, setBellOpen] = useState(false);
  const { theme } = useBrandTheme();
  const primary = theme.primaryColor || "#4361EE";

  const notifications = [
    { id: 1, text: "Priya Sharma sent a WhatsApp message", time: "2m ago", read: false },
    { id: 2, text: "New call — transcription ready", time: "15m ago", read: false },
    { id: 3, text: "QA score dropped below 70 for Agent Ravi", time: "1h ago", read: true },
  ];
  const unread = notifications.filter((n) => !n.read).length;

  return (
    <header
      className="h-14 flex items-center justify-between px-4 flex-shrink-0"
      style={{
        backgroundColor: "var(--brand-topbar-bg, #0D1B4B)",
        borderBottom: "1px solid rgba(255,255,255,0.05)",
        paddingTop: "env(safe-area-inset-top)",
      }}
    >
      {/* Logo mark + page title */}
      <div className="flex items-center gap-3 min-w-0">
        <Link href="/dashboard" className="flex-shrink-0">
          {theme.logoDarkUrl || theme.logoUrl ? (
            <img
              src={theme.logoDarkUrl ?? theme.logoUrl}
              alt={theme.companyName}
              className="h-7 w-auto object-contain"
            />
          ) : (
            <div
              className="w-7 h-7 rounded-lg flex items-center justify-center font-bold text-xs flex-shrink-0"
              style={{
                background: `linear-gradient(135deg, ${primary}, var(--brand-primary-dark, ${primary}))`,
                color: "#ffffff",
              }}
            >
              {(theme.companyName ?? "HA").slice(0, 2).toUpperCase()}
            </div>
          )}
        </Link>
        <PageTitle />
      </div>

      {/* Right actions */}
      <div className="flex items-center gap-1">
        {/* Bell */}
        <div className="relative">
          <button
            onClick={() => setBellOpen(!bellOpen)}
            className="relative w-9 h-9 rounded-xl flex items-center justify-center text-white/40 hover:text-white/70 active:bg-white/5 transition-colors"
          >
            <Bell size={18} />
            {unread > 0 && (
              <span
                className="absolute top-1.5 right-1.5 w-2 h-2 rounded-full"
                style={{ backgroundColor: primary }}
              />
            )}
          </button>

          {bellOpen && (
            <>
              <div className="fixed inset-0 z-30" onClick={() => setBellOpen(false)} />
              <div className="absolute right-0 top-full mt-2 z-40 w-80 max-w-[calc(100vw-2rem)] bg-[#0f2744] border border-white/10 rounded-2xl shadow-2xl shadow-black/40 overflow-hidden">
                <div className="flex items-center justify-between px-4 py-3 border-b border-white/6">
                  <span className="text-xs font-bold text-white/60 uppercase tracking-wider">Notifications</span>
                  {unread > 0 && (
                    <span className="text-[10px] bg-indigo-500/20 text-indigo-400 px-2 py-0.5 rounded-full font-bold">
                      {unread} new
                    </span>
                  )}
                </div>
                {notifications.map((n) => (
                  <div
                    key={n.id}
                    className={`px-4 py-3 border-b border-white/4 last:border-0 ${!n.read ? "bg-indigo-500/4" : ""}`}
                  >
                    <p className="text-xs text-white/70 leading-relaxed mb-1">{n.text}</p>
                    <p className="text-[10px] text-white/25">{n.time}</p>
                  </div>
                ))}
                <div className="px-4 py-3 text-center">
                  <button className="text-xs text-indigo-400 font-semibold">Mark all read</button>
                </div>
              </div>
            </>
          )}
        </div>

        {/* User avatar */}
        <Link
          href="/dashboard/profile"
          className="w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold ml-1"
          style={{ backgroundColor: primary, color: "#0a1b30" }}
        >
          {user?.name?.[0]?.toUpperCase() ?? "U"}
        </Link>
      </div>
    </header>
  );
}
