"use client";
import { useState } from "react";
import { usePathname } from "next/navigation";
import Link from "next/link";
import { signOut } from "next-auth/react";
import {
  Home, Inbox, Phone, Users, Building2,
  Sparkles, BarChart2, Zap, Link2, Settings,
  HelpCircle, User, LogOut, ChevronDown, ChevronRight,
  MessageSquare, AtSign, Bot,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { canSeeNav, type Resource } from "@/lib/permissions";
import { useBrandTheme } from "@/components/providers/BrandThemeProvider";
import { useInboxStore } from "@/store/inbox";

// ─── Nav structure ────────────────────────────────────────────────────────────

interface NavItem {
  label: string;
  href: string;
  icon: React.ComponentType<{ size?: number; className?: string }>;
  resource: Resource;
  children?: { label: string; href: string; icon?: React.ComponentType<{ size?: number; className?: string }> }[];
}

const NAV_ITEMS: NavItem[] = [
  {
    label: "Home",
    href: "/dashboard",
    icon: Home,
    resource: "dashboard",
  },
  {
    label: "Inbox",
    href: "/dashboard/inbox",
    icon: Inbox,
    resource: "inbox",
    children: [
      { label: "Conversations", href: "/dashboard/inbox",             icon: MessageSquare },
      { label: "WhatsApp",      href: "/dashboard/inbox?ch=whatsapp", icon: MessageSquare },
      { label: "Instagram",     href: "/dashboard/inbox?ch=instagram", icon: AtSign },
      { label: "AI Concierge",   href: "/dashboard/inbox?ch=ai",                    icon: Bot },
      { label: "Channel Manager", href: "/dashboard/inbox/channel-manager",          icon: Building2 },
    ],
  },
  {
    label: "Calls",
    href: "/dashboard/calls",
    icon: Phone,
    resource: "calls",
  },
  {
    label: "Guests",
    href: "/dashboard/guests",
    icon: Users,
    resource: "guests",
    children: [
      { label: "Guest 360",   href: "/dashboard/guests" },
      { label: "Segments",    href: "/dashboard/guests?view=segments" },
      { label: "VIP Guests",  href: "/dashboard/guests?view=vip" },
    ],
  },
  {
    label: "Portfolio",
    href: "/dashboard/properties",
    icon: Building2,
    resource: "properties",
    children: [
      { label: "Properties",        href: "/dashboard/properties" },
      { label: "Calendar",          href: "/dashboard/portfolio/calendar" },
      { label: "Rate Calculator",   href: "/dashboard/calculator" },
    ],
  },
  {
    label: "AI Intelligence",
    href: "/dashboard/qa",
    icon: Sparkles,
    resource: "analytics",
  },
  {
    label: "Analytics",
    href: "/dashboard/analytics",
    icon: BarChart2,
    resource: "analytics",
    children: [
      { label: "Dashboard",   href: "/dashboard/analytics" },
      { label: "Guests",      href: "/dashboard/analytics/guests" },
      { label: "Channels",    href: "/dashboard/analytics/channels" },
      { label: "Campaigns",   href: "/dashboard/analytics/campaigns" },
      { label: "Properties",  href: "/dashboard/analytics/properties" },
      { label: "Operations",  href: "/dashboard/analytics/operations" },
      { label: "AI Intel",      href: "/dashboard/analytics/ai" },
      { label: "Intent",        href: "/dashboard/analytics/intent" },
      { label: "Objections",    href: "/dashboard/analytics/objections" },
      { label: "Attribution",   href: "/dashboard/analytics/attribution" },
      { label: "Occ Forecast",  href: "/dashboard/analytics/forecasting/occupancy" },
      { label: "Rev Forecast",  href: "/dashboard/analytics/forecasting/revenue" },
      { label: "Pricing",       href: "/dashboard/analytics/forecasting/pricing" },
      { label: "Churn Risk",    href: "/dashboard/analytics/forecasting/churn" },
      { label: "Cohorts",       href: "/dashboard/analytics/forecasting/cohorts" },
      { label: "AI Recs",       href: "/dashboard/analytics/forecasting/recommendations" },
      { label: "✦ Ask HAIP",   href: "/dashboard/analytics/ask" },
    ],
  },
  {
    label: "Automations",
    href: "/dashboard/automations",
    icon: Zap,
    resource: "settings",
  },
  {
    label: "Integrations",
    href: "/dashboard/settings/integrations",
    icon: Link2,
    resource: "settings",
  },
  {
    label: "Settings",
    href: "/dashboard/settings",
    icon: Settings,
    resource: "settings",
  },
];

const BOTTOM_ITEMS = [
  { label: "Support", href: "/dashboard/help",    icon: HelpCircle },
  { label: "Account", href: "/dashboard/profile", icon: User },
];

// ─── Component ────────────────────────────────────────────────────────────────

interface SidebarProps {
  user?: { name?: string | null; email?: string | null; role?: string };
}

export function Sidebar({ user }: SidebarProps) {
  const pathname = usePathname();
  const role = user?.role ?? "";
  const { theme } = useBrandTheme();
  const { conversations } = useInboxStore();
  const [expanded, setExpanded] = useState<string | null>(null);

  const unreadCount = conversations.filter(c => (c as any).unread_count > 0).length;

  function isActive(href: string) {
    if (href === "/dashboard") return pathname === "/dashboard";
    // strip query for path matching
    const hrefPath = href.split("?")[0];
    return pathname === hrefPath || pathname.startsWith(hrefPath + "/");
  }

  function toggleExpand(label: string) {
    setExpanded(e => e === label ? null : label);
  }

  const companyName = theme.companyName ?? "HAIP";

  return (
    <aside
      className="w-[220px] flex flex-col h-full flex-shrink-0 select-none"
      style={{
        background: "var(--haip-sidebar)",
        borderRight: "1px solid var(--haip-sidebar-border)",
      }}
    >
      {/* ── Logo / brand ─────────────────────────────────────────────────── */}
      <Link
        href="/dashboard"
        className="px-4 py-4 flex items-center gap-3 flex-shrink-0 transition-opacity hover:opacity-80"
        style={{ borderBottom: "1px solid var(--haip-border)" }}
      >
        {theme.logoUrl ? (
          <img
            src={theme.logoUrl}
            alt={companyName}
            className="h-7 w-auto object-contain"
          />
        ) : (
          <>
            <div
              className="w-8 h-8 rounded-xl flex items-center justify-center flex-shrink-0"
              style={{
                background: "linear-gradient(135deg, #0F766E, #059669)",
                boxShadow: "0 2px 8px rgba(15,118,110,0.25)",
              }}
            >
              {/* Grid icon matching Stitch logo */}
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                <rect x="1" y="1" width="6" height="6" rx="1.5" fill="white" fillOpacity="0.9" />
                <rect x="9" y="1" width="6" height="6" rx="1.5" fill="white" fillOpacity="0.6" />
                <rect x="1" y="9" width="6" height="6" rx="1.5" fill="white" fillOpacity="0.6" />
                <rect x="9" y="9" width="6" height="6" rx="1.5" fill="white" fillOpacity="0.9" />
              </svg>
            </div>
            <div className="min-w-0">
              <div
                className="font-bold text-[14px] tracking-tight leading-tight"
                style={{
                  fontFamily: "var(--font-display), sans-serif",
                  color: "var(--haip-fg)",
                }}
              >
                {companyName}
              </div>
              <div className="text-[10px] leading-tight mt-0.5" style={{ color: "var(--haip-fg-subtle)" }}>
                Hospitality AI
              </div>
            </div>
          </>
        )}
      </Link>

      {/* ── Navigation ───────────────────────────────────────────────────── */}
      <nav className="flex-1 overflow-y-auto py-3 px-3 space-y-0.5 haip-scrollbar">
        {NAV_ITEMS.filter(item => canSeeNav(role, item.resource)).map(item => {
          const active = isActive(item.href);
          const Icon = item.icon;
          const isInbox = item.href === "/dashboard/inbox";
          const hasChildren = (item.children?.length ?? 0) > 0;
          const isExpanded = expanded === item.label || active;

          return (
            <div key={item.href}>
              {/* Main nav item */}
              <div className="flex items-center">
                <Link
                  href={item.href}
                  className={cn("haip-nav-item flex-1", active && "active")}
                  onClick={() => hasChildren && setExpanded(e => e === item.label ? null : item.label)}
                >
                  <span className="flex-shrink-0" style={{ color: active ? "#0F766E" : "#9CA3AF" }}>
                    <Icon size={15} />
                  </span>
                  <span className="flex-1 truncate">{item.label}</span>
                  {isInbox && unreadCount > 0 && (
                    <span
                      className="flex-shrink-0 min-w-[18px] h-[18px] rounded-full flex items-center justify-center text-[10px] font-bold"
                      style={{ background: "#0F766E", color: "#fff", padding: "0 4px" }}
                    >
                      {unreadCount > 9 ? "9+" : unreadCount}
                    </span>
                  )}
                  {hasChildren && (
                    <span style={{ color: "#9CA3AF" }}>
                      {isExpanded
                        ? <ChevronDown size={12} />
                        : <ChevronRight size={12} />}
                    </span>
                  )}
                </Link>
              </div>

              {/* Sub-items */}
              {hasChildren && isExpanded && (
                <div className="mt-0.5 space-y-0.5 pl-1">
                  {item.children!.map(child => {
                    const childActive = pathname === child.href.split("?")[0];
                    const ChildIcon = child.icon;
                    return (
                      <Link
                        key={child.href}
                        href={child.href}
                        className={cn("haip-nav-sub", childActive && "active")}
                      >
                        {ChildIcon && (
                          <span style={{ color: childActive ? "#0F766E" : "#9CA3AF" }}>
                            <ChildIcon size={12} />
                          </span>
                        )}
                        {child.label}
                      </Link>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}
      </nav>

      {/* ── Bottom section ────────────────────────────────────────────────── */}
      <div
        className="px-3 pb-3 pt-2 space-y-0.5"
        style={{ borderTop: "1px solid var(--haip-border)" }}
      >
        {BOTTOM_ITEMS.map(item => {
          const Icon = item.icon;
          const active = isActive(item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn("haip-nav-item", active && "active")}
            >
              <span style={{ color: active ? "#0F766E" : "#9CA3AF" }}><Icon size={14} /></span>
              <span>{item.label}</span>
            </Link>
          );
        })}

        {/* User row with sign out */}
        <div
          className="flex items-center gap-2.5 px-2.5 py-2 rounded-lg mt-1 cursor-default"
          style={{ color: "var(--haip-fg-muted)" }}
        >
          <div
            className="w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold flex-shrink-0 text-white"
            style={{ background: "#0F766E" }}
          >
            {user?.name?.[0]?.toUpperCase() ?? "U"}
          </div>
          <div className="flex-1 min-w-0">
            <div className="text-[12.5px] font-semibold truncate" style={{ color: "var(--haip-fg)" }}>
              {user?.name ?? "User"}
            </div>
            <div className="text-[10px] capitalize" style={{ color: "var(--haip-fg-subtle)" }}>
              {user?.role ?? "concierge"}
            </div>
          </div>
          <button
            onClick={() => signOut({ callbackUrl: "/login" })}
            className="flex-shrink-0 w-6 h-6 flex items-center justify-center rounded transition-colors"
            style={{ color: "#9CA3AF" }}
            onMouseEnter={e => { (e.currentTarget as HTMLElement).style.color = "var(--haip-fg)"; }}
            onMouseLeave={e => { (e.currentTarget as HTMLElement).style.color = "#9CA3AF"; }}
            title="Sign out"
          >
            <LogOut size={13} />
          </button>
        </div>
      </div>
    </aside>
  );
}
