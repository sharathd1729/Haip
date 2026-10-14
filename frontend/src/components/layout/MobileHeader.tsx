"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useTheme } from "next-themes";
import { useQuery } from "@tanstack/react-query";
import { Bell, Sun, Moon, Monitor } from "@/lib/icons";
import { useBrandTheme } from "@/components/providers/BrandThemeProvider";
import { useNotificationsStore } from "@/store/useNotificationsStore";
import api from "@/lib/api";

const ROUTE_LABELS: Record<string, string> = {
  dashboard:    "Home",
  "my-day":     "My day",
  portfolio:    "Portfolio",
  calendar:     "Calendar",
  marketing:    "Marketing",
  inbox:        "Inbox",
  calls:        "Calls",
  leads:        "Leads360",
  inquiries:    "Inquiries",
  guests:       "Bookings",
  bookings:     "Bookings",
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
  // Dynamic-id routes (/dashboard/leads/{inquiryId}, /dashboard/calls/{id},
  // /dashboard/guests/{id}, etc.) have no ROUTE_LABELS entry for their last
  // segment -- it's a raw uuid/id, not a route name. Walking back to the
  // nearest labeled ancestor avoids showing that id verbatim as the title
  // (the page body already shows the guest/record's real name).
  let label: string | undefined;
  for (let i = segments.length - 1; i >= 0; i--) {
    label = ROUTE_LABELS[segments[i]];
    if (label) break;
  }
  if (!label) {
    const last = segments[segments.length - 1] ?? "dashboard";
    label = last.charAt(0).toUpperCase() + last.slice(1);
  }
  return (
    <span className="font-semibold text-sm tracking-tight" style={{ color: "var(--haip-fg)" }}>
      {label}
    </span>
  );
}

function MobileThemeToggle() {
  const { theme, setTheme } = useTheme();
  function cycle() {
    if (theme === "light") setTheme("dark");
    else if (theme === "dark") setTheme("system");
    else setTheme("light");
  }
  const Icon = theme === "light" ? Sun : theme === "dark" ? Moon : Monitor;
  return (
    <button
      onClick={cycle}
      aria-label="Change theme"
      className="w-9 h-9 rounded-lg flex items-center justify-center transition-colors duration-150 active:bg-muted"
      style={{ color: "var(--haip-fg-subtle)" }}
    >
      <Icon size={16} />
    </button>
  );
}

interface MobileHeaderProps {
  user?: { name?: string | null; email?: string | null; role?: string };
}

function timeAgo(ts: number): string {
  const secs = Math.floor((Date.now() - ts) / 1000);
  if (secs < 60) return "just now";
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
  if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`;
  return `${Math.floor(secs / 86400)}d ago`;
}

export function MobileHeader({ user }: MobileHeaderProps) {
  const [bellOpen, setBellOpen] = useState(false);
  const { theme } = useBrandTheme();
  const router = useRouter();
  const items = useNotificationsStore(s => s.items);
  const markAllRead = useNotificationsStore(s => s.markAllRead);
  const unreadCount = useNotificationsStore(s => s.unreadCount);
  const unread = unreadCount();
  const { data: me } = useQuery({
    queryKey: ["users", "me"],
    queryFn: () => api.get("/users/me").then(r => r.data),
    staleTime: 60_000,
  });

  return (
    <header
      className="flex items-center justify-between px-4 flex-shrink-0 bg-background shadow-[0_1px_0_var(--haip-border),0_2px_8px_rgba(0,0,0,0.05)]"
      style={{
        // Fixed (does not scroll). The device's top inset (notch, camera cut-out, foldable cover display) is added to the
        // 44px bar instead of eating into it, so the logo and title are never clipped.
        minHeight: "calc(2.75rem + env(safe-area-inset-top))",
        paddingTop: "env(safe-area-inset-top)",
        paddingLeft: "max(1rem, env(safe-area-inset-left))",
        paddingRight: "max(1rem, env(safe-area-inset-right))",
      }}
    >
      {/* Logo mark + page title */}
      <div className="flex items-center gap-3 min-w-0">
        <Link href="/dashboard" className="flex-shrink-0">
          {theme.logoDarkUrl || theme.logoUrl ? (
            <img
              src={theme.logoDarkUrl ?? theme.logoUrl}
              alt={theme.companyName}
              className="h-6 w-auto object-contain"
            />
          ) : (
            <div
              className="w-7 h-7 rounded-lg flex items-center justify-center font-bold text-xs flex-shrink-0"
              style={{
                background: "var(--primary)",
                color: "var(--primary-foreground)",
              }}
            >
              {(theme.companyName ?? "HA").slice(0, 2).toUpperCase()}
            </div>
          )}
        </Link>
        <PageTitle />
      </div>

      {/* Right actions */}
      <div className="flex items-center gap-0.5">
        <MobileThemeToggle />

        {/* Bell */}
        <div className="relative">
          <button
            onClick={() => setBellOpen(!bellOpen)}
            aria-label="Notifications" aria-expanded={bellOpen}
            className="relative w-9 h-9 rounded-lg flex items-center justify-center transition-colors duration-150 active:bg-muted"
            style={{ color: "var(--haip-fg-subtle)" }}
          >
            <Bell size={16} />
            {unread > 0 && (
              <span
                className="absolute top-1.5 right-1.5 w-[7px] h-[7px] rounded-full"
                style={{ background: "var(--haip-red)" }}
              />
            )}
          </button>

          {bellOpen && (
            <>
              <div className="fixed inset-0 z-30" onClick={() => setBellOpen(false)} />
              <div
                className="absolute right-0 top-full mt-2 z-40 w-80 max-w-[calc(100vw-2rem)] rounded-xl overflow-hidden shadow-md"
                style={{
                  background: "var(--haip-card)",
                  border: "1px solid var(--haip-border)",
                }}
              >
                <div
                  className="flex items-center justify-between px-4 py-3"
                  style={{ borderBottom: "1px solid var(--haip-border)" }}
                >
                  <span
                    className="text-[10px] font-semibold uppercase tracking-widest"
                    style={{ color: "var(--haip-fg-subtle)" }}
                  >
                    Notifications
                  </span>
                  {unread > 0 && (
                    <span
                      className="text-[10px] px-2 py-0.5 rounded-full font-semibold"
                      style={{
                        background: "color-mix(in srgb, var(--primary) 10%, transparent)",
                        color: "var(--primary)",
                      }}
                    >
                      {unread} new
                    </span>
                  )}
                </div>
                {items.length === 0 ? (
                  <div className="px-4 py-6 text-center">
                    <p className="text-xs" style={{ color: "var(--haip-fg-subtle)" }}>No notifications yet</p>
                  </div>
                ) : (
                  items.map(n => (
                    <div
                      key={n.id}
                      className="px-4 py-3 cursor-pointer active:bg-muted"
                      style={{
                        borderBottom: "1px solid var(--haip-border)",
                        background: !n.read
                          ? "color-mix(in srgb, var(--primary) 4%, transparent)"
                          : "transparent",
                      }}
                      onClick={() => { setBellOpen(false); router.push(n.url); }}
                    >
                      <p className="text-xs font-semibold mb-0.5" style={{ color: "var(--haip-fg)" }}>
                        {n.title}
                      </p>
                      <p className="text-xs leading-relaxed mb-1" style={{ color: "var(--haip-fg-2)" }}>
                        {n.body}
                      </p>
                      <p className="text-[10px]" style={{ color: "var(--haip-fg-subtle)" }}>{timeAgo(n.ts)}</p>
                    </div>
                  ))
                )}
                {items.length > 0 && (
                  <div className="px-4 py-3 text-center">
                    <button
                      onClick={markAllRead}
                      className="text-xs font-semibold"
                      style={{ color: "var(--primary)" }}
                    >
                      Mark all read
                    </button>
                  </div>
                )}
              </div>
            </>
          )}
        </div>

        {/* User avatar */}
        {me?.avatar_url ? (
          <Link href="/dashboard/profile" className="ml-0.5 flex-shrink-0">
            <img src={me.avatar_url} alt={user?.name ?? "User"} className="w-8 h-8 rounded-full object-cover" />
          </Link>
        ) : (
          <Link
            href="/dashboard/profile"
            className="w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold ml-0.5"
            style={{
              background: "var(--primary)",
              color: "var(--primary-foreground)",
            }}
          >
            {user?.name?.[0]?.toUpperCase() ?? "U"}
          </Link>
        )}
      </div>
    </header>
  );
}
