"use client";

import { clearTokenCache } from "@/lib/api";
import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { signOut } from "next-auth/react";
import {
  Inbox, Phone, Users, Menu, X,
  Home, Target, Building2, Calendar, Calculator,
  MessageSquare, Megaphone, UserCheck, GitBranch,
  Sparkles, FileDown, Star, Shield, Zap,
  Settings, Plug2, CreditCard, UserCircle, HelpCircle,
  Palette, FileText, LogOut,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { canSeeNav, type Resource } from "@/lib/permissions";
import { useBrandTheme } from "@/components/providers/BrandThemeProvider";
import { useBusinessType } from "@/components/providers/WorkspaceProvider";
import { useInboxStore } from "@/store/inbox";
import { AppVersionRow } from "@/components/AppVersionRow";

interface MobileNavProps {
  user?: { name?: string | null; email?: string | null; role?: string };
}

// The 4 bottom-tab items (always visible). Leads360 sits here rather than
// Guests because it's the flagship M4 pipeline view and had zero mobile
// entry point before this — Guests is still one tap away under Sales below.
const BOTTOM_TABS = [
  { label: "Home",     href: "/dashboard",       icon: Home,   resource: "dashboard" as Resource },
  { label: "Inbox",    href: "/dashboard/inbox", icon: Inbox,  resource: "inbox"     as Resource },
  { label: "Calls",    href: "/dashboard/calls", icon: Phone,  resource: "calls"     as Resource },
  { label: "Leads360", href: "/dashboard/leads", icon: Target, resource: "guests"    as Resource },
];

// Full nav for the "More" sheet — mirrors Sidebar's NAV_ITEMS/sections so
// nothing reachable on desktop is mobile-only-via-URL.
const ALL_SECTIONS = [
  {
    // "Dashboard" and "My Dashboards" removed 2026-08-08 -- deactivated,
    // being rebuilt from scratch. "Home" bottom-tab (below) still points at
    // /dashboard, which now redirects elsewhere.
    label: "Workspace",
    items: [
      { label: "Inbox",         href: "/dashboard/inbox",       icon: Inbox,          resource: "inbox"     as Resource, live: "inbox" as const },
      { label: "Calls",         href: "/dashboard/calls",       icon: Phone,          resource: "calls"     as Resource },
    ],
  },
  {
    label: "Sales",
    items: [
      { label: "Leads360",  href: "/dashboard/leads",      icon: Target,   resource: "guests"     as Resource },
      { label: "Guests",    href: "/dashboard/guests",     icon: Users,    resource: "guests"     as Resource },
      { label: "Inquiries", href: "/dashboard/inquiries",  icon: FileText, resource: "inquiries"  as Resource },
    ],
  },
  {
    label: "Portfolio",
    items: [
      { label: "Properties",      href: "/dashboard/properties",          icon: Building2,  resource: "properties" as Resource, hideForBusinessTypes: ["caravan"] },
      { label: "Calendar",        href: "/dashboard/portfolio/calendar",  icon: Calendar,   resource: "properties" as Resource },
      { label: "Rate Calculator", href: "/dashboard/calculator",          icon: Calculator, resource: "properties" as Resource, hideForBusinessTypes: ["caravan"] },
    ],
  },
  {
    label: "Messaging",
    items: [
      { label: "Templates",    href: "/dashboard/messaging/templates",   icon: MessageSquare, resource: "templates"   as Resource },
      { label: "Campaigns",    href: "/dashboard/messaging/campaigns",   icon: Megaphone,     resource: "campaigns"   as Resource },
      { label: "Subscribers",  href: "/dashboard/messaging/subscribers", icon: UserCheck,     resource: "subscribers" as Resource },
      { label: "Flow Builder", href: "/dashboard/messaging/flows",       icon: GitBranch,     resource: "flows"       as Resource },
    ],
  },
  {
    // "Analytics" removed 2026-08-08 -- deactivated, being rebuilt from
    // scratch. "Ask HAIP" is a separate module, unaffected. "AI Insights"
    // reactivated 2026-08-15 as its own module ("ai_insights", migration
    // 075), also independent of the analytics deactivation.
    label: "Intelligence",
    items: [
      { label: "AI Insights", href: "/dashboard/insights",      icon: Sparkles,  resource: "dashboard"   as Resource },
      { label: "Ask HAIP",    href: "/dashboard/analytics/ask", icon: Sparkles,  resource: "analytics"   as Resource },
      { label: "Reports",     href: "/dashboard/reports",       icon: FileDown,  resource: "reports"     as Resource },
      { label: "QA & Scores", href: "/dashboard/qa",            icon: Star,      resource: "qa"          as Resource },
      { label: "Compliance",  href: "/dashboard/compliance",    icon: Shield,    resource: "compliance"  as Resource },
    ],
  },
  {
    label: "Configure",
    items: [
      { label: "Automations",  href: "/dashboard/automations",           icon: Zap,     resource: "settings"     as Resource },
      { label: "Integrations", href: "/dashboard/settings/integrations", icon: Plug2,   resource: "integrations" as Resource },
      { label: "Settings",     href: "/dashboard/settings",              icon: Settings, resource: "settings"    as Resource },
    ],
  },
  {
    label: "Account",
    items: [
      { label: "Team",           href: "/dashboard/settings/team",     icon: Users,      resource: "users"    as Resource },
      { label: "Branding",       href: "/dashboard/settings/branding", icon: Palette,    resource: "branding" as Resource },
      { label: "Billing",        href: "/dashboard/billing",           icon: CreditCard, resource: "billing"  as Resource },
      { label: "Profile",        href: "/dashboard/profile",           icon: UserCircle, resource: "profile"  as Resource },
      { label: "Help & Support", href: "/dashboard/help",              icon: HelpCircle, resource: "help"     as Resource },
    ],
  },
];

export function MobileNav({ user }: MobileNavProps) {
  const pathname = usePathname();
  const role = user?.role ?? "";
  const businessType = useBusinessType();
  const [sheetOpen, setSheetOpen] = useState(false);
  const { theme } = useBrandTheme();
  const { conversations } = useInboxStore();

  const primary = theme.primaryColor || "#14b8a6";
  const unreadCount = conversations.filter(c => (c as any).unread_count > 0).length;

  function isActive(href: string) {
    return pathname === href || (href !== "/dashboard" && pathname.startsWith(href + "/"));
  }

  return (
    <>
      {/* ── Bottom tab bar ───────────────────────────────────────────── */}
      <nav
        className="md:hidden fixed bottom-0 left-0 right-0 z-50 flex items-stretch"
        style={{
          backgroundColor: "var(--brand-sidebar-bg, #0a1b30)",
          borderTop: "1px solid rgba(255,255,255,0.07)",
          paddingBottom: "env(safe-area-inset-bottom)",
        }}
      >
        {BOTTOM_TABS.filter(t => canSeeNav(role, t.resource)).map((tab) => {
          const Icon = tab.icon;
          const active = isActive(tab.href);
          const badge = tab.href === "/dashboard/inbox" && unreadCount > 0
            ? (unreadCount > 9 ? "9+" : String(unreadCount))
            : null;
          return (
            <Link
              key={tab.href}
              href={tab.href}
              className="flex-1 flex flex-col items-center justify-center py-2 gap-0.5 min-h-[52px] relative transition-opacity active:opacity-60"
            >
              <span className="relative">
                <Icon
                  size={22}
                  style={{ color: active ? primary : "rgba(255,255,255,0.35)" }}
                />
                {badge && (
                  <span
                    className="absolute -top-1 -right-2 text-[9px] font-bold px-1 rounded-full leading-tight"
                    style={{ backgroundColor: primary, color: "#0a1b30" }}
                  >
                    {badge}
                  </span>
                )}
              </span>
              <span
                className="text-[10px] font-medium"
                style={{ color: active ? primary : "rgba(255,255,255,0.30)" }}
              >
                {tab.label}
              </span>
              {active && (
                <span
                  className="absolute top-0 left-1/2 -translate-x-1/2 w-8 h-0.5 rounded-full"
                  style={{ backgroundColor: primary }}
                />
              )}
            </Link>
          );
        })}

        {/* More button */}
        <button
          onClick={() => setSheetOpen(true)}
          className="flex-1 flex flex-col items-center justify-center py-2 gap-0.5 min-h-[52px] transition-opacity active:opacity-60"
        >
          <Menu size={22} style={{ color: "rgba(255,255,255,0.35)" }} />
          <span className="text-[10px] font-medium" style={{ color: "rgba(255,255,255,0.30)" }}>
            More
          </span>
        </button>
      </nav>

      {/* ── Full-screen nav sheet ─────────────────────────────────────── */}
      {sheetOpen && (
        <div className="md:hidden fixed inset-0 z-[60] flex">
          {/* Backdrop */}
          <div
            className="absolute inset-0 bg-black/60 backdrop-blur-sm"
            onClick={() => setSheetOpen(false)}
          />

          {/* Sheet panel */}
          <div
            className="relative ml-auto w-72 h-full flex flex-col overflow-y-auto"
            style={{
              backgroundColor: "var(--brand-sidebar-bg, #0a1b30)",
              borderLeft: "1px solid rgba(255,255,255,0.07)",
            }}
          >
            {/* Header */}
            <div
              className="flex items-center justify-between px-5 py-4 flex-shrink-0"
              style={{ borderBottom: "1px solid rgba(255,255,255,0.07)" }}
            >
              <span className="font-bold text-white text-base">{theme.companyName ?? "HAIP"}</span>
              <button
                onClick={() => setSheetOpen(false)}
                className="w-8 h-8 flex items-center justify-center rounded-lg text-white/40 hover:text-white hover:bg-white/5 transition-colors"
              >
                <X size={18} />
              </button>
            </div>

            {/* Nav sections */}
            <nav className="flex-1 py-2 overflow-y-auto">
              {ALL_SECTIONS.map((section) => {
                const visible = section.items.filter(
                  (item: { resource: Resource; hideForBusinessTypes?: string[] }) =>
                    canSeeNav(role, item.resource) &&
                    (!businessType || !item.hideForBusinessTypes?.includes(businessType))
                );
                if (visible.length === 0) return null;
                return (
                  <div key={section.label} className="px-3 py-1">
                    <div
                      className="text-[10px] uppercase tracking-widest font-bold px-2 py-2"
                      style={{ color: "rgba(255,255,255,0.25)" }}
                    >
                      {section.label}
                    </div>
                    {visible.map((item) => {
                      const Icon = item.icon;
                      const active = isActive(item.href);
                      const badge = "live" in item && item.live === "inbox" && unreadCount > 0
                        ? (unreadCount > 9 ? "9+" : String(unreadCount))
                        : null;
                      return (
                        <Link
                          key={item.href + item.label}
                          href={item.href}
                          onClick={() => setSheetOpen(false)}
                          className="flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium transition-colors mb-0.5"
                          style={{
                            backgroundColor: active ? `rgba(${hexToRgb(primary)}, 0.12)` : "transparent",
                            color: active ? "#ffffff" : "rgba(255,255,255,0.55)",
                          }}
                        >
                          <Icon
                            size={17}
                            style={{ color: active ? primary : "rgba(255,255,255,0.30)" }}
                          />
                          <span className="flex-1">{item.label}</span>
                          {badge && (
                            <span
                              className="text-[10px] px-1.5 py-0.5 rounded-full font-semibold"
                              style={{ backgroundColor: `rgba(${hexToRgb(primary)}, 0.2)`, color: primary }}
                            >
                              {badge}
                            </span>
                          )}
                        </Link>
                      );
                    })}
                  </div>
                );
              })}
            </nav>

            {/* User footer */}
            <div
              className="p-4 flex-shrink-0"
              style={{
                borderTop: "1px solid rgba(255,255,255,0.07)",
                paddingBottom: "calc(1rem + env(safe-area-inset-bottom))",
              }}
            >
              <div className="flex items-center gap-3 mb-3">
                <div
                  className="w-9 h-9 rounded-full flex items-center justify-center text-sm font-bold flex-shrink-0"
                  style={{ backgroundColor: primary, color: "#0a1b30" }}
                >
                  {user?.name?.[0]?.toUpperCase() ?? "U"}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="text-white text-sm font-semibold truncate">{user?.name ?? "User"}</div>
                  <div className="text-[11px] text-white/35 truncate">{user?.email ?? ""}</div>
                </div>
              </div>
              <button
                onClick={() => { clearTokenCache(); signOut({ callbackUrl: "/login" }); }}
                className="w-full flex items-center gap-2.5 px-3 py-2.5 text-sm text-red-400 hover:text-red-300 hover:bg-red-500/8 rounded-xl transition-colors"
              >
                <LogOut size={15} />
                Sign out
              </button>
              <div className="mt-1 pt-2" style={{ borderTop: "1px solid rgba(255,255,255,0.07)" }}>
                <AppVersionRow dark />
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

// Utility: hex → "r, g, b" string for rgba()
function hexToRgb(hex: string): string {
  const cleaned = hex.replace("#", "");
  const r = parseInt(cleaned.substring(0, 2), 16);
  const g = parseInt(cleaned.substring(2, 4), 16);
  const b = parseInt(cleaned.substring(4, 6), 16);
  if (isNaN(r) || isNaN(g) || isNaN(b)) return "20, 184, 166"; // teal fallback
  return `${r}, ${g}, ${b}`;
}
