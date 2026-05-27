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
    <span className="font-semibold text-gray-800 text-sm">
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
  const primary = theme.primaryColor || "#14b8a6";

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
        backgroundColor: "var(--brand-topbar-bg, #FFFFFF)",
        borderBottom: "1px solid #E5E7EB",
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
              className="h-9 w-auto object-contain"
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
            className="relative w-9 h-9 rounded-xl flex items-center justify-center text-gray-500 hover:text-gray-700 active:bg-gray-100 transition-colors"
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
              <div className="absolute right-0 top-full mt-2 z-40 w-80 max-w-[calc(100vw-2rem)] bg-white border border-gray-200 rounded-2xl shadow-xl overflow-hidden">
                <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100">
                  <span className="text-xs font-bold text-gray-400 uppercase tracking-wider">Notifications</span>
                  {unread > 0 && (
                    <span className="text-[10px] bg-teal-50 text-teal-600 px-2 py-0.5 rounded-full font-bold">
                      {unread} new
                    </span>
                  )}
                </div>
                {notifications.map((n) => (
                  <div
                    key={n.id}
                    className={`px-4 py-3 border-b border-gray-50 last:border-0 ${!n.read ? "bg-teal-50/50" : ""}`}
                  >
                    <p className="text-xs text-gray-700 leading-relaxed mb-1">{n.text}</p>
                    <p className="text-[10px] text-gray-400">{n.time}</p>
                  </div>
                ))}
                <div className="px-4 py-3 text-center">
                  <button className="text-xs text-teal-600 font-semibold">Mark all read</button>
                </div>
              </div>
            </>
          )}
        </div>

        {/* User avatar */}
        <Link
          href="/dashboard/profile"
          className="w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold ml-1"
          style={{ backgroundColor: primary, color: "#ffffff" }}
        >
          {user?.name?.[0]?.toUpperCase() ?? "U"}
        </Link>
      </div>
    </header>
  );
}
