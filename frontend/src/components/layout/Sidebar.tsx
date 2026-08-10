"use client";
import { clearTokenCache } from "@/lib/api";
import { useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import Link from "next/link";
import { signOut } from "next-auth/react";
import {
  Inbox, Phone, Users, Building2,
  Sparkles, BarChart2, Zap, Link2, Settings,
  HelpCircle, LogOut, ChevronDown, ChevronRight,
  MessageSquare, AtSign, Bot, Target, Megaphone, UserCheck, GitBranch, FileText,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { canSeeNav, type Resource } from "@/lib/permissions";
import { useBrandTheme } from "@/components/providers/BrandThemeProvider";
import { useBusinessType } from "@/components/providers/WorkspaceProvider";
import { useInboxStore } from "@/store/inbox";
import { AppVersionRow } from "@/components/AppVersionRow";

// ─── Nav structure ────────────────────────────────────────────────────────────

interface NavItem {
  label: string;
  href: string;
  icon: React.ComponentType<{ size?: number; className?: string }>;
  resource: Resource;
  section?: string;
  /** Business verticals (tenants.business_type) that should NOT see this item.
   *  null/unknown business_type hides nothing. */
  hideForBusinessTypes?: string[];
  children?: {
    label: string;
    href: string;
    icon?: React.ComponentType<{ size?: number; className?: string }>;
    hideForBusinessTypes?: string[];
    /** Only shown to users with role === "owner" -- e.g. the free-form
     *  analyst's Phase 2 early-access gate. Backend still enforces this
     *  independently; this is purely to avoid showing a dead-end link. */
    ownerOnly?: boolean;
  }[];
}

const NAV_ITEMS: NavItem[] = [
  // "Dashboard" (/dashboard) and "My Dashboards" (/dashboard/dashboards)
  // deactivated 2026-08-08 -- Owner Dashboard + widget builder being rebuilt
  // from scratch. Backend router-level require_module("analytics") 403s
  // both; removed from nav so there's no dead link. Restore alongside
  // re-adding "analytics" to DEFAULT_MODULE_CODES.
  {
    label: "Inbox",
    href: "/dashboard/inbox",
    icon: Inbox,
    resource: "inbox",
    children: [
      { label: "Conversations",   href: "/dashboard/inbox",                    icon: MessageSquare },
      { label: "WhatsApp",        href: "/dashboard/inbox?ch=whatsapp",        icon: MessageSquare },
      { label: "Instagram",       href: "/dashboard/inbox?ch=instagram",       icon: AtSign },
      { label: "AI Concierge",    href: "/dashboard/inbox?ch=ai",              icon: Bot,       hideForBusinessTypes: ["caravan"] },
      { label: "Channel Manager", href: "/dashboard/inbox/channel-manager",    icon: Building2, hideForBusinessTypes: ["caravan"] },
    ],
  },
  {
    label: "Calls",
    href: "/dashboard/calls",
    icon: Phone,
    resource: "calls",
  },
  {
    label: "Leads360",
    href: "/dashboard/leads",
    icon: Target,
    resource: "guests",
    section: "Sales",
  },
  {
    label: "Guests",
    href: "/dashboard/guests",
    icon: Users,
    resource: "guests",
    children: [
      { label: "Guest 360",  href: "/dashboard/guests" },
      { label: "Segments",   href: "/dashboard/guests?view=segments" },
      { label: "VIP Guests", href: "/dashboard/guests?view=vip" },
    ],
  },
  {
    label: "Portfolio",
    href: "/dashboard/properties",
    icon: Building2,
    resource: "properties",
    children: [
      { label: "Properties",      href: "/dashboard/properties",         hideForBusinessTypes: ["caravan"] },
      { label: "Calendar",        href: "/dashboard/portfolio/calendar" },
      { label: "Rate Calculator", href: "/dashboard/calculator",         hideForBusinessTypes: ["caravan"] },
    ],
  },
  {
    label: "Messaging",
    href: "/dashboard/messaging/templates",
    icon: Megaphone,
    resource: "settings",
    section: "Channels",
    children: [
      { label: "Templates",    href: "/dashboard/messaging/templates",   icon: FileText },
      { label: "Campaigns",    href: "/dashboard/messaging/campaigns",   icon: Megaphone },
      { label: "Subscribers",  href: "/dashboard/messaging/subscribers", icon: UserCheck },
      { label: "Flow Builder", href: "/dashboard/messaging/flows",       icon: GitBranch },
    ],
  },
  {
    // "Analytics" and "Charts" children removed 2026-08-08 -- analytics
    // pages deactivated, being rebuilt from scratch. "Exports" (raw report
    // generation, not "analytics") is unaffected and kept.
    label: "Reports",
    href: "/dashboard/reports",
    icon: BarChart2,
    resource: "analytics",
    section: "Intelligence",
  },
  {
    label: "Ask HAIP",
    // Point at the real page, not the /dashboard/ask-haip redirect stub: the
    // stub bounces to this URL, after which neither isActive() nor childActive
    // matches "/dashboard/ask-haip", so the nav item silently stopped
    // highlighting. Also matches the Reports/Free-Form siblings below.
    href: "/dashboard/analytics/ask",
    icon: Sparkles,
    resource: "analytics",
    children: [
      { label: "Ask",       href: "/dashboard/analytics/ask" },
      { label: "Reports",   href: "/dashboard/analytics/ask/reports" },
      { label: "Free-Form", href: "/dashboard/analytics/ask/freeform", ownerOnly: true },
    ],
  },
  {
    label: "Automations",
    href: "/dashboard/automations",
    icon: Zap,
    resource: "settings",
    section: "Configure",
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
];

// ─── Component ────────────────────────────────────────────────────────────────

interface SidebarProps {
  user?: { name?: string | null; email?: string | null; role?: string };
}

export function Sidebar({ user }: SidebarProps) {
  const businessType = useBusinessType();
  const pathname = usePathname();
  const router = useRouter();
  const role = user?.role ?? "";
  const { theme } = useBrandTheme();
  const { conversations } = useInboxStore();
  const [expanded, setExpanded] = useState<string | null>(null);

  const unreadCount = conversations.filter(c => (c as any).unread_count > 0).length;

  function isActive(href: string) {
    if (href === "/dashboard") return pathname === "/dashboard";
    const hrefPath = href.split("?")[0];
    return pathname === hrefPath || pathname.startsWith(hrefPath + "/");
  }

  // B7: prefetch on hover/focus instead of eagerly. Every nav Link here is
  // always in the viewport (the sidebar never scrolls out of view), so
  // Next's default viewport-triggered prefetch fires for the full nav list
  // (main items + expanded children + bottom items) on every mount --
  // prefetch={false} below turns that off; this fires it back on, but only
  // for the one link the user is actually about to click.
  function prefetchOnHover(href: string) {
    router.prefetch(href);
  }

  const companyName = theme.companyName ?? "HAIP";

  // Track which section labels have been rendered to avoid duplicates
  const renderedSections = new Set<string>();

  const visibleItems = NAV_ITEMS
    .filter(item => canSeeNav(role, item.resource))
    .filter(item => !businessType || !item.hideForBusinessTypes?.includes(businessType))
    .map(item => ({
      ...item,
      children: item.children?.filter(
        c => (!businessType || !c.hideForBusinessTypes?.includes(businessType))
          && (!c.ownerOnly || role === "owner")
      ),
    }));

  return (
    <aside
      className="w-[240px] flex flex-col h-full flex-shrink-0 select-none"
      style={{
        background: "var(--haip-sidebar)",
        borderRight: "1px solid var(--haip-sidebar-border)",
      }}
    >
      {/* ── Logo / brand ─────────────────────────────────────────────────── */}
      <Link
        href="/dashboard"
        className="px-4 py-[14px] flex items-center gap-3 flex-shrink-0 transition-opacity hover:opacity-80"
        style={{ borderBottom: "1px solid var(--haip-sidebar-border)" }}
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
              className="w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0"
              style={{
                background: "linear-gradient(135deg, var(--haip-sidebar-accent), var(--haip-primary))",
                boxShadow: "0 2px 8px rgba(20,184,166,0.3)",
              }}
            >
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
                  color: "var(--haip-sidebar-fg-active)",
                }}
              >
                {companyName}
              </div>
              <div className="text-[10px] leading-tight mt-0.5" style={{ color: "var(--haip-sidebar-fg-subtle)" }}>
                Hospitality AI
              </div>
            </div>
          </>
        )}
      </Link>

      {/* ── Navigation ───────────────────────────────────────────────────── */}
      <nav className="flex-1 overflow-y-auto py-3 px-3 haip-scrollbar" style={{ gap: 0 }}>
        {visibleItems.map((item, idx) => {
          const active = isActive(item.href);
          const Icon = item.icon;
          const isInbox = item.href === "/dashboard/inbox";
          const hasChildren = (item.children?.length ?? 0) > 0;
          const isExpanded = expanded === item.label || active;

          // Section label — render once per section
          let sectionLabel: React.ReactNode = null;
          if (item.section && !renderedSections.has(item.section)) {
            renderedSections.add(item.section);
            sectionLabel = (
              <p
                key={`section-${item.section}`}
                className="text-[10px] font-bold uppercase tracking-widest px-3 mb-1 mt-4 first:mt-2"
                style={{ color: "var(--haip-sidebar-fg-subtle)" }}
              >
                {item.section}
              </p>
            );
          }

          return (
            <div key={item.href}>
              {sectionLabel}

              {/* Main nav item */}
              <div className="mb-0.5">
                <Link
                  href={item.href}
                  prefetch={false}
                  onMouseEnter={() => prefetchOnHover(item.href)}
                  onFocus={() => prefetchOnHover(item.href)}
                  className={cn("haip-nav-item", active && "active")}
                  onClick={() => hasChildren && setExpanded(e => e === item.label ? null : item.label)}
                >
                  {/* Icon colour is driven by .haip-nav-item svg rules in
                      globals.css so hover/active states stay in one place */}
                  <span className="flex-shrink-0">
                    <Icon size={15} />
                  </span>
                  <span className="flex-1 truncate">{item.label}</span>

                  {/* Inbox unread badge */}
                  {isInbox && unreadCount > 0 && (
                    <span
                      className="flex-shrink-0 min-w-[18px] h-[18px] rounded-full flex items-center justify-center text-[10px] font-bold"
                      style={{
                        background: "var(--haip-sidebar-accent)",
                        color: "#0B1F3A",
                        padding: "0 4px",
                      }}
                    >
                      {unreadCount > 9 ? "9+" : unreadCount}
                    </span>
                  )}

                  {/* Expand chevron */}
                  {hasChildren && (
                    <span style={{ color: "var(--haip-sidebar-fg-subtle)" }}>
                      {isExpanded
                        ? <ChevronDown size={12} />
                        : <ChevronRight size={12} />}
                    </span>
                  )}
                </Link>
              </div>

              {/* Sub-items */}
              {hasChildren && isExpanded && (
                <div className="mb-1 space-y-0.5 pl-1">
                  {item.children!.map(child => {
                    const childActive = pathname === child.href.split("?")[0];
                    const ChildIcon = child.icon;
                    return (
                      <Link
                        key={child.href}
                        href={child.href}
                        prefetch={false}
                        onMouseEnter={() => prefetchOnHover(child.href)}
                        onFocus={() => prefetchOnHover(child.href)}
                        className={cn("haip-nav-sub", childActive && "active")}
                      >
                        {ChildIcon && (
                          <span style={{ color: childActive ? "var(--haip-sidebar-accent)" : "var(--haip-sidebar-fg-subtle)" }}>
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
        style={{ borderTop: "1px solid var(--haip-sidebar-border)" }}
      >
        {BOTTOM_ITEMS.map(item => {
          const Icon = item.icon;
          const active = isActive(item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
              prefetch={false}
              onMouseEnter={() => prefetchOnHover(item.href)}
              onFocus={() => prefetchOnHover(item.href)}
              className={cn("haip-nav-item", active && "active")}
            >
              <span>
                <Icon size={14} />
              </span>
              <span>{item.label}</span>
            </Link>
          );
        })}

        {/* User row */}
        <div
          className="flex items-center gap-2.5 px-2.5 py-2 rounded-lg mt-1 cursor-default"
          style={{ color: "var(--haip-sidebar-fg)" }}
        >
          {/* Avatar */}
          <div
            className="w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold flex-shrink-0"
            style={{
              background: "linear-gradient(135deg, var(--haip-sidebar-accent), var(--haip-primary))",
              color: "#0B1F3A",
            }}
          >
            {user?.name?.[0]?.toUpperCase() ?? "U"}
          </div>

          {/* Name + role pill */}
          <div className="flex-1 min-w-0">
            <div className="text-[12.5px] font-semibold truncate" style={{ color: "var(--haip-sidebar-fg-active)" }}>
              {user?.name ?? "User"}
            </div>
            <span
              className="inline-block text-[9px] font-medium capitalize px-1.5 py-0.5 rounded-full mt-0.5"
              style={{
                background: "var(--haip-sidebar-active-bg)",
                color: "var(--haip-sidebar-accent)",
              }}
            >
              {user?.role ?? "concierge"}
            </span>
          </div>

          {/* Sign out */}
          <button
            onClick={() => { clearTokenCache(); signOut({ callbackUrl: "/login" }); }}
            className="flex-shrink-0 w-6 h-6 flex items-center justify-center rounded transition-colors duration-150"
            style={{ color: "var(--haip-sidebar-fg-subtle)" }}
            onMouseEnter={e => { (e.currentTarget as HTMLElement).style.color = "var(--haip-sidebar-fg-active)"; }}
            onMouseLeave={e => { (e.currentTarget as HTMLElement).style.color = "var(--haip-sidebar-fg-subtle)"; }}
            title="Sign out"
          >
            <LogOut size={13} />
          </button>
        </div>

        <AppVersionRow />
      </div>
    </aside>
  );
}
