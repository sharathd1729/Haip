"use client";
import api, { clearTokenCache } from "@/lib/api";
import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { signOut } from "next-auth/react";
import { Calendar, CreditCard, Key, Inbox, Phone, Users, Building2, Home, BarChart2, Zap, Link2, Settings, HelpCircle, LogOut, ChevronDown, ChevronRight, ChevronLeft, MessageSquare, AtSign, Bot, Target, Megaphone, Send, FileText, LayoutDashboard, ListChecks, BookmarkIcon, TrendingUp, MessageCircle, User, Shuffle, BarChart3 } from "@/lib/icons";
import { UserCheck, GitBranch } from "lucide-react";
import { cn } from "@/lib/utils";
import { BOOKING_READ_ROLES, REVENUE_READ_ROLES, canSeeNav, type Resource } from "@/lib/permissions";
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
  /** Business verticals (tenants.business_type) that should NOT see this item.
   *  null/unknown business_type hides nothing. */
  hideForBusinessTypes?: string[];
  /** Show only to these roles (the page's data is restricted server-side too). */
  onlyRoles?: string[];
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

interface NavGroup {
  /** null = ungrouped, rendered with no section header (the "General" items
   *  every workspace opens to first). */
  section: string | null;
  items: NavItem[];
}

// AppFlowy-inspired structural change: sections used to be an inline
// `section` string on the first item of each group, inferred purely from
// array order -- real, but not an actual grouped data structure. Same
// items, same visual order, now a real NavGroup[] tree (workspace-style
// grouping, matching AppFlowy's sidebar sections).
const NAV_GROUPS: NavGroup[] = [
  // Five sections, ordered by how often a day is spent in them (Redesign Phase 1).
  // Today answers "who is waiting on me" (My day) and "how are we doing" (Dashboard).
  {
    section: "Today",
    items: [
      { label: "My day", href: "/dashboard/my-day", icon: ListChecks, resource: "inbox" },
      { label: "Home", href: "/dashboard", icon: LayoutDashboard, resource: "dashboard" },
    ],
  },
  {
    section: "Conversations",
    items: [
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
      { label: "Calls", href: "/dashboard/calls", icon: Phone, resource: "calls" },
      // Self-service for every role, deliberately not nested under
      // "Settings" (owner/manager only) -- see the "whatsapp_personal"
      // resource in permissions.ts for why this is a separate resource key.
      { label: "My WhatsApp", href: "/dashboard/settings/whatsapp-personal", icon: MessageCircle, resource: "whatsapp_personal" },
      {
        label: "Messaging",
        href: "/dashboard/messaging",
        icon: Send,
        resource: "settings",
        children: [
          { label: "Overview",     href: "/dashboard/messaging",             icon: BarChart3 },
          { label: "Templates",    href: "/dashboard/messaging/templates",   icon: FileText },
          { label: "Campaigns",    href: "/dashboard/messaging/campaigns",   icon: Megaphone },
          { label: "Subscribers",  href: "/dashboard/messaging/subscribers", icon: UserCheck },
          { label: "Flow Builder", href: "/dashboard/messaging/flows",       icon: GitBranch },
          { label: "Saved Replies", href: "/dashboard/settings/saved-replies", icon: BookmarkIcon },
        ],
      },
    ],
  },
  {
    section: "Sales",
    items: [
      { label: "Leads360", href: "/dashboard/leads", icon: Target, resource: "guests" },
      // Calendar is a daily tool, so it is a main item (it was the second child of Portfolio).
      { label: "Calendar", href: "/dashboard/portfolio/calendar", icon: Calendar, resource: "properties" },
      { label: "Bookings", href: "/dashboard/bookings", icon: BookmarkIcon, resource: "guests", onlyRoles: BOOKING_READ_ROLES },
      { label: "Targets", href: "/dashboard/targets", icon: TrendingUp, resource: "guests", onlyRoles: REVENUE_READ_ROLES },
      {
        label: "Portfolio",
        href: "/dashboard/properties",
        icon: Home,
        resource: "properties",
        hideForBusinessTypes: ["caravan"],     // its only children (Properties, Rate Calculator) are hidden for caravan workspaces
        children: [
          { label: "Properties",      href: "/dashboard/properties",         hideForBusinessTypes: ["caravan"] },
          { label: "Rate Calculator", href: "/dashboard/calculator",         hideForBusinessTypes: ["caravan"] },
        ],
      },
    ],
  },
  {
    section: "Insights",
    items: [
      // "Analytics" and "Charts" children removed 2026-08-08 -- analytics
      // pages deactivated, being rebuilt from scratch. "Exports" (raw
      // report generation, not "analytics") is unaffected and kept.
      { label: "Reports", href: "/dashboard/reports", icon: BarChart2, resource: "reports" },
      { label: "Instagram Insights", href: "/dashboard/instagram-insights", icon: AtSign, resource: "analytics" },
      { label: "Marketing", href: "/dashboard/marketing", icon: Megaphone, resource: "analytics", onlyRoles: ["owner", "manager", "marketing"] },
    ],
  },
  {
    // Rarely-used configuration pages live under one "Settings" item instead of
    // six top-level rows, so the rail stays short.
    section: "Workspace",
    items: [
      { label: "Automations", href: "/dashboard/automations", icon: Zap, resource: "settings" },
      {
        label: "Settings",
        href: "/dashboard/settings",
        icon: Settings,
        resource: "settings",
        children: [
          { label: "General",         href: "/dashboard/settings",                  icon: Settings },
          { label: "Integrations",    href: "/dashboard/settings/integrations",     icon: Link2 },
          { label: "Lead assignment", href: "/dashboard/settings/lead-assignment",  icon: Shuffle },
          { label: "Calendar sync",   href: "/dashboard/settings/calendar-sync",    icon: Calendar },
          { label: "Payments",        href: "/dashboard/settings/payments",         icon: CreditCard },
          { label: "Developers",      href: "/dashboard/settings/developers",       icon: Key },
        ],
      },
    ],
  },
];

// Profile was previously only reachable via the TopBar avatar dropdown --
// a real discoverability gap on desktop (reported live) compared to
// mobile's dedicated "Account" section in MobileNav, which already lists
// it plainly. Universal like Support -- no resource gate, every role has
// their own profile.
const BOTTOM_ITEMS = [
  { label: "Profile", href: "/dashboard/profile", icon: User, kind: "account" as const },
  { label: "Support", href: "/dashboard/help",    icon: HelpCircle, kind: "support" as const },
];

// ─── Component ────────────────────────────────────────────────────────────────

interface SidebarProps {
  user?: { name?: string | null; email?: string | null; role?: string };
}

const COLLAPSE_STORAGE_KEY = "haip_sidebar_collapsed";

export function Sidebar({ user }: SidebarProps) {
  const businessType = useBusinessType();
  const pathname = usePathname();
  const router = useRouter();
  const role = user?.role ?? "";
  const { theme } = useBrandTheme();
  const { conversations } = useInboxStore();
  const { data: me } = useQuery({
    queryKey: ["users", "me"],
    queryFn: () => api.get("/users/me").then(r => r.data),
    staleTime: 60_000,
  });
  const [expanded, setExpanded] = useState<string | null>(null);
  // AppFlowy-inspired collapsible rail. The first render must match the
  // server's (expanded), so the saved choice is read after mount; reading
  // localStorage in the useState initializer caused a hydration mismatch
  // (React #418) for anyone who had collapsed it. The width transition is
  // switched on only after that read, so the rail snaps instead of animating.
  const [collapsed, setCollapsed] = useState(false);
  const [railReady, setRailReady] = useState(false);
  useEffect(() => {
    const saved = window.localStorage.getItem(COLLAPSE_STORAGE_KEY);
    // No choice made yet: on tablet widths (768-1023px, where the rail replaces the phone tab bar) start as the slim rail so
    // the page keeps the room; wider screens start expanded. Toggling stores the person's choice.
    setCollapsed(saved === "1" ? true : saved === "0" ? false : window.innerWidth < 1024);
    setRailReady(true);
  }, []);

  function toggleCollapsed() {
    setCollapsed(c => {
      const next = !c;
      window.localStorage.setItem(COLLAPSE_STORAGE_KEY, next ? "1" : "0");
      return next;
    });
  }

  const unreadCount = conversations.filter(c => (c as any).unread_count > 0).length;

  // How many things are waiting on this person (same source as the My day page, so the badge and
  // the list always agree). Only fetched for roles that can see My day.
  const canSeeMyDay = canSeeNav(role, "inbox");
  const { data: queue } = useQuery<{ total: number }>({
    queryKey: ["work-queue", ""],
    queryFn: () => api.get("/work-queue").then(r => r.data),
    staleTime: 30_000,
    refetchInterval: 60_000,
    enabled: canSeeMyDay,
  });
  const badgeFor = (href: string): number =>
    href === "/dashboard/inbox" ? unreadCount : href === "/dashboard/my-day" ? (queue?.total ?? 0) : 0;

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

  const visibleGroups = NAV_GROUPS
    .map(group => ({
      section: group.section,
      items: group.items
        .filter(item => canSeeNav(role, item.resource))
        .filter(item => !businessType || !item.hideForBusinessTypes?.includes(businessType))
        .filter(item => !item.onlyRoles || item.onlyRoles.includes(role))
        .map(item => ({
          ...item,
          children: item.children?.filter(
            c => (!businessType || !c.hideForBusinessTypes?.includes(businessType))
              && (!c.ownerOnly || role === "owner")
          ),
        })),
    }))
    .filter(group => group.items.length > 0);

  return (
    <aside
      className={cn(
        "flex flex-col h-full flex-shrink-0 select-none",
        railReady && "transition-[width] duration-150 ease-out",
        collapsed ? "w-[64px]" : "w-[240px]",
      )}
      style={{
        background: "var(--haip-sidebar)",
        borderRight: "1px solid var(--haip-sidebar-border)",
      }}
    >
      {/* ── Logo / brand + collapse toggle ──────────────────────────────── */}
      <div
        className="px-4 py-[14px] flex items-center gap-2 flex-shrink-0"
        style={{ borderBottom: "1px solid var(--haip-sidebar-border)" }}
      >
        <Link
          href="/dashboard"
          className={cn(
            "flex items-center gap-3 min-w-0 transition-opacity hover:opacity-80",
            collapsed ? "flex-1 justify-center" : "flex-1",
          )}
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
              {!collapsed && (
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
              )}
            </>
          )}
        </Link>

        {/* AppFlowy-style collapse rail toggle. Kept visible even in
            collapsed state (as its own row below) so there's always a way
            back to expanded. */}
        {!collapsed && (
          <button
            type="button"
            onClick={toggleCollapsed}
            className="flex-shrink-0 w-6 h-6 flex items-center justify-center rounded transition-colors duration-150"
            style={{ color: "var(--haip-sidebar-fg-subtle)" }}
            onMouseEnter={e => { (e.currentTarget as HTMLElement).style.color = "var(--haip-sidebar-fg-active)"; }}
            onMouseLeave={e => { (e.currentTarget as HTMLElement).style.color = "var(--haip-sidebar-fg-subtle)"; }}
            title="Collapse sidebar"
          >
            <ChevronLeft size={14} />
          </button>
        )}
      </div>

      {collapsed && (
        <button
          type="button"
          onClick={toggleCollapsed}
          className="mx-auto mt-2 flex-shrink-0 w-6 h-6 flex items-center justify-center rounded transition-colors duration-150"
          style={{ color: "var(--haip-sidebar-fg-subtle)" }}
          onMouseEnter={e => { (e.currentTarget as HTMLElement).style.color = "var(--haip-sidebar-fg-active)"; }}
          onMouseLeave={e => { (e.currentTarget as HTMLElement).style.color = "var(--haip-sidebar-fg-subtle)"; }}
          title="Expand sidebar"
        >
          <ChevronRight size={14} />
        </button>
      )}

      {/* ── Navigation ───────────────────────────────────────────────────── */}
      <nav className="flex-1 overflow-y-auto py-3 px-3 haip-scrollbar" style={{ gap: 0 }}>
        {visibleGroups.map((group, groupIdx) => (
          <div key={group.section ?? `group-${groupIdx}`}>
            {group.section && !collapsed && (
              <p
                className="text-[10px] font-bold uppercase tracking-widest px-3 mb-1 mt-4 first:mt-2"
                style={{ color: "var(--haip-sidebar-fg-subtle)" }}
              >
                {group.section}
              </p>
            )}
            {group.section && collapsed && groupIdx > 0 && (
              <div className="mx-2 my-2 border-t" style={{ borderColor: "var(--haip-sidebar-border)" }} />
            )}

            {group.items.map(item => {
              const active = isActive(item.href);
              const Icon = item.icon;
              const badge = badgeFor(item.href);
              const hasChildren = (item.children?.length ?? 0) > 0;
              const isExpanded = !collapsed && (expanded === item.label || active);

              return (
                <div key={item.href}>
                  {/* Main nav item */}
                  <div className="mb-0.5">
                    <Link
                      href={item.href}
                      prefetch={false}
                      onMouseEnter={() => prefetchOnHover(item.href)}
                      onFocus={() => prefetchOnHover(item.href)}
                      className={cn("haip-nav-item", active && "active", collapsed && "justify-center")}
                      onClick={() => !collapsed && hasChildren && setExpanded(e => e === item.label ? null : item.label)}
                      title={collapsed ? item.label : undefined}
                    >
                      {/* Icon colour is driven by .haip-nav-item svg rules in
                          globals.css so hover/active states stay in one place */}
                      <span className="flex-shrink-0">
                        <Icon size={15} />
                      </span>
                      {!collapsed && <span className="flex-1 truncate">{item.label}</span>}

                      {/* Count badge: unread conversations on Inbox, things waiting on you on My day */}
                      {badge > 0 && (
                        <span
                          className="flex-shrink-0 min-w-[18px] h-[18px] rounded-full flex items-center justify-center text-[10px] font-bold"
                          style={{
                            background: "var(--haip-sidebar-accent)",
                            color: "#0B1F3A",
                            padding: "0 4px",
                            position: collapsed ? "absolute" : "static",
                            top: collapsed ? 2 : undefined,
                            right: collapsed ? 2 : undefined,
                          }}
                        >
                          {collapsed ? "" : (badge > 99 ? "99+" : badge)}
                        </span>
                      )}

                      {/* Expand chevron */}
                      {hasChildren && !collapsed && (
                        <span style={{ color: "var(--haip-sidebar-fg-subtle)" }}>
                          {isExpanded
                            ? <ChevronDown size={12} />
                            : <ChevronRight size={12} />}
                        </span>
                      )}
                    </Link>
                  </div>

                  {/* Sub-items -- hidden entirely in collapsed mode (AppFlowy's
                      collapsed rail shows icon-only top-level items, not a
                      flyout tree) */}
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
          </div>
        ))}
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
              className={cn("haip-nav-item", active && "active", collapsed && "justify-center",
                // Support is help, Profile is you: they must not read as the same kind of row.
                item.kind === "support" && "mt-1 border border-dashed border-[var(--haip-sidebar-border)]")}
              title={collapsed ? item.label : undefined}
              aria-label={item.kind === "support" ? "Support and help" : "Your profile"}
            >
              <span style={item.kind === "support" ? { color: "var(--haip-sidebar-accent)" } : undefined}>
                <Icon size={14} />
              </span>
              {!collapsed && <span>{item.kind === "support" ? "Help & support" : "My profile"}</span>}
            </Link>
          );
        })}

        {/* User row */}
        <div
          className={cn(
            "flex items-center gap-2.5 py-2 rounded-lg mt-1 cursor-default",
            collapsed ? "justify-center px-0" : "px-2.5",
          )}
          style={{ color: "var(--haip-sidebar-fg)" }}
          title={collapsed ? (user?.name ?? "User") : undefined}
        >
          {/* Avatar */}
          {me?.avatar_url ? (
            <img
              src={me.avatar_url}
              alt={user?.name ?? "User"}
              className="w-7 h-7 rounded-full object-cover flex-shrink-0"
            />
          ) : (
            <div
              className="w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold flex-shrink-0"
              style={{
                background: "linear-gradient(135deg, var(--haip-sidebar-accent), var(--haip-primary))",
                color: "#0B1F3A",
              }}
            >
              {user?.name?.[0]?.toUpperCase() ?? "U"}
            </div>
          )}

          {!collapsed && (
            <>
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
            </>
          )}
        </div>

        {!collapsed && <AppVersionRow />}
      </div>
    </aside>
  );
}
