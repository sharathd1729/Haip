"use client";
// Phone top bar, Hospitality Hybrid: a menu button (opens every page the person can reach), the page's name, then theme,
// notifications and the account. 52px plus the device's top inset; globals.css hides the in-page title under 640px
// because this bar already names the page, so every route needs a ROUTE_LABELS entry.
import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useTheme } from "next-themes";
import { useQuery } from "@tanstack/react-query";
import { Bell, Menu, Sun, Moon, Monitor } from "@/lib/icons";
import { cn } from "@/lib/utils";
import { useNotificationsStore } from "@/store/useNotificationsStore";
import api from "@/lib/api";
import { UserAvatar } from "@/components/crm/UserAvatar";
import { MobileMenuSheet } from "./MobileNav";

const ROUTE_LABELS: Record<string, string> = {
  dashboard:    "Home",
  "my-day":     "My day",
  portfolio:    "Portfolio",
  calendar:     "Calendar",
  marketing:    "Marketing",
  studio:       "Marketing Studio",
  inbox:        "Inbox",
  calls:        "Calls",
  leads:        "Leads",
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
  // Static page titles are hidden on phones (this bar names the page), so every route needs its own name here.
  automations:  "Automations",
  calculator:   "Rate calculator",
  "calendar-sync": "Calendar sync",
  "channel-manager": "Channel manager",
  developers:   "Developers",
  "instagram-insights": "Instagram insights",
  ivr:          "Call routing",
  knowledge:    "AI knowledge base",
  "lead-assignment": "Lead assignment",
  "leads-activity": "Lead activity",
  "mcp-access": "AI assistants",
  "meta-quality": "Meta quality",
  operations:   "Operations",
  payments:     "Payments",
  permissions:  "Roles & permissions",
  "saved-replies": "Saved replies",
  targets:      "Targets",
  "whatsapp-personal": "Personal WhatsApp",
};

function PageTitle() {
  const pathname = usePathname();
  const segments = pathname.split("/").filter(Boolean);
  // Dynamic-id routes (/dashboard/leads/{inquiryId}, /dashboard/calls/{id}, ...) have no label for their last segment
  // (a raw id); walk back to the nearest labelled ancestor instead of showing the id. The page body names the record.
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
    <span className="min-w-0 truncate font-[family-name:var(--font-display)] text-[17px] font-semibold tracking-[-0.01em] text-[var(--haip-fg)]">
      {label}
    </span>
  );
}

const ICON_BTN = "relative flex size-11 shrink-0 items-center justify-center rounded-xl text-[var(--haip-icon-neutral)] transition-colors active:bg-[var(--hover-bg)]";

function MobileThemeToggle() {
  const { theme, setTheme } = useTheme();
  function cycle() {
    if (theme === "light") setTheme("dark");
    else if (theme === "dark") setTheme("system");
    else setTheme("light");
  }
  const Icon = theme === "light" ? Sun : theme === "dark" ? Moon : Monitor;
  return <button type="button" onClick={cycle} aria-label="Change theme" className={ICON_BTN}><Icon size={18} /></button>;
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
  const [menuOpen, setMenuOpen] = useState(false);
  const pathname = usePathname();
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
  useEffect(() => { setMenuOpen(false); setBellOpen(false); }, [pathname]);
  useEffect(() => {
    if (!menuOpen) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setMenuOpen(false); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [menuOpen]);

  return (
    <>
      <header
        className="flex flex-shrink-0 items-center gap-0.5 border-b border-[var(--haip-border)] bg-[var(--haip-card)]"
        style={{
          // Fixed (does not scroll). The top inset (notch, cut-out) is added to the 52px bar instead of eating into it.
          minHeight: "calc(3.25rem + env(safe-area-inset-top))",
          paddingTop: "env(safe-area-inset-top)",
          paddingLeft: "max(0.25rem, env(safe-area-inset-left))",
          paddingRight: "max(0.25rem, env(safe-area-inset-right))",
        }}
      >
        <button type="button" onClick={() => setMenuOpen(true)} aria-label="Open menu" aria-expanded={menuOpen} className={ICON_BTN}>
          <Menu size={21} />
        </button>
        <div className="flex min-w-0 flex-1 items-center pl-0.5"><PageTitle /></div>

        <MobileThemeToggle />

        <div className="relative">
          <button type="button" onClick={() => setBellOpen(!bellOpen)} aria-expanded={bellOpen}
            aria-label={unread ? `Notifications, ${unread} new` : "Notifications"} className={ICON_BTN}>
            <Bell size={18} />
            {unread > 0 && <span className="absolute right-2.5 top-2.5 size-2 rounded-full bg-[var(--haip-accent)] ring-2 ring-[var(--haip-card)]" />}
          </button>

          {bellOpen && (
            <>
              <div className="fixed inset-0 z-30" onClick={() => setBellOpen(false)} />
              <div className="absolute right-0 top-full z-40 mt-2 w-80 max-w-[calc(100vw-1rem)] overflow-hidden rounded-2xl border border-[var(--haip-border)] bg-[var(--haip-card)] shadow-[var(--haip-shadow-lg)]">
                <div className="flex items-center justify-between border-b border-[var(--haip-border)] px-4 py-3">
                  <span className="font-[family-name:var(--font-display)] text-[15px] font-semibold text-[var(--haip-fg)]">Notifications</span>
                  {unread > 0 && <span className="rounded-full bg-[var(--haip-primary-tint)] px-2 py-0.5 text-[11px] font-semibold text-primary">{unread} new</span>}
                </div>
                {items.length === 0 ? (
                  <p className="px-4 py-6 text-center text-[13px] text-[var(--haip-fg-subtle)]">No notifications yet</p>
                ) : (
                  <div className="max-h-[60dvh] overflow-y-auto">
                    {items.map(n => (
                      <button type="button" key={n.id}
                        className={cn("block w-full border-b border-[var(--haip-border)] px-4 py-3 text-left active:bg-[var(--hover-bg)]", !n.read && "bg-[var(--haip-primary-tint)]")}
                        onClick={() => { setBellOpen(false); router.push(n.url); }}>
                        <p className="mb-0.5 text-[13px] font-semibold text-[var(--haip-fg)]">{n.title}</p>
                        <p className="mb-1 text-[13px] leading-relaxed text-[var(--haip-fg-2)]">{n.body}</p>
                        <p className="text-[11px] text-[var(--haip-fg-subtle)]">{timeAgo(n.ts)}</p>
                      </button>
                    ))}
                  </div>
                )}
                {items.length > 0 && (
                  <div className="px-4 py-1 text-center">
                    <button type="button" onClick={markAllRead} className="min-h-11 px-3 text-[13px] font-semibold text-primary">Mark all read</button>
                  </div>
                )}
              </div>
            </>
          )}
        </div>

        <Link href="/dashboard/profile" aria-label="Your profile" className="flex size-11 shrink-0 items-center justify-center">
          <UserAvatar name={user?.name} photoUrl={me?.avatar_url} size="sm" className="size-8" />
        </Link>
      </header>
      <MobileMenuSheet open={menuOpen} onClose={() => setMenuOpen(false)} user={user} />
    </>
  );
}
