"use client";
import { usePathname } from "next/navigation";
import Link from "next/link";
import { signOut } from "next-auth/react";
import {
  LayoutDashboard, Phone, MessageSquare, Users,
  BarChart2, Star, Settings, LogOut, Inbox,
  Home, Shield, Plug2, Zap, Megaphone,
  UserCheck, GitBranch, FileDown, CreditCard,
  HelpCircle, UserCircle, Palette,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { canSeeNav, type Resource } from "@/lib/permissions";
import { useBrandTheme } from "@/components/providers/BrandThemeProvider";
import { brightness } from "@/lib/brandTheme";

interface NavItem {
  label: string;
  href: string;
  icon: React.ReactNode;
  resource: Resource;
  badge?: string | number;
}

const navSections: { label: string; items: NavItem[] }[] = [
  {
    label: "Workspace",
    items: [
      { label: "Dashboard",  href: "/dashboard",           icon: <LayoutDashboard size={16} />, resource: "dashboard" },
      { label: "Inbox",      href: "/dashboard/inbox",     icon: <Inbox size={16} />,           resource: "inbox",    badge: "3" },
      { label: "Calls",      href: "/dashboard/calls",     icon: <Phone size={16} />,           resource: "calls" },
    ],
  },
  {
    label: "CRM",
    items: [
      { label: "Inquiries",  href: "/dashboard/inquiries",  icon: <Zap size={16} />,        resource: "inquiries" },
      { label: "Guests",     href: "/dashboard/guests",     icon: <Users size={16} />,       resource: "guests" },
      { label: "Properties", href: "/dashboard/properties", icon: <Home size={16} />,        resource: "properties" },
    ],
  },
  {
    label: "Messaging",
    items: [
      { label: "Templates",    href: "/dashboard/messaging/templates",   icon: <MessageSquare size={16} />, resource: "templates" },
      { label: "Campaigns",    href: "/dashboard/messaging/campaigns",   icon: <Megaphone size={16} />,     resource: "campaigns" },
      { label: "Subscribers",  href: "/dashboard/messaging/subscribers", icon: <UserCheck size={16} />,     resource: "subscribers" },
      { label: "Flow Builder", href: "/dashboard/messaging/flows",       icon: <GitBranch size={16} />,     resource: "flows" },
    ],
  },
  {
    label: "Intelligence",
    items: [
      { label: "Analytics",   href: "/dashboard/analytics",   icon: <BarChart2 size={16} />, resource: "analytics" },
      { label: "Reports",     href: "/dashboard/reports",     icon: <FileDown size={16} />,  resource: "reports" },
      { label: "QA & Scores", href: "/dashboard/qa",          icon: <Star size={16} />,      resource: "qa" },
      { label: "Compliance",  href: "/dashboard/compliance",  icon: <Shield size={16} />,    resource: "compliance" },
    ],
  },
  {
    label: "Account",
    items: [
      { label: "Settings",      href: "/dashboard/settings",              icon: <Settings size={16} />,    resource: "settings" },
      { label: "Integrations",  href: "/dashboard/settings/integrations", icon: <Plug2 size={16} />,       resource: "integrations" },
      { label: "Team",          href: "/dashboard/settings/team",         icon: <Users size={16} />,       resource: "users" },
      { label: "Branding",      href: "/dashboard/settings/branding",     icon: <Palette size={16} />,     resource: "branding" as Resource },
      { label: "Billing",       href: "/dashboard/billing",               icon: <CreditCard size={16} />,  resource: "billing" },
      { label: "Profile",       href: "/dashboard/profile",               icon: <UserCircle size={16} />,  resource: "profile" },
      { label: "Help & Support",href: "/dashboard/help",                  icon: <HelpCircle size={16} />,  resource: "help" },
    ],
  },
];

interface SidebarProps {
  user?: { name?: string | null; email?: string | null; role?: string };
}

export function Sidebar({ user }: SidebarProps) {
  const pathname = usePathname();
  const role = user?.role ?? "";
  const { theme } = useBrandTheme();

  // Derived colors from CSS variables (already applied to :root)
  const sidebarBg   = "var(--brand-sidebar-bg)";
  const primary     = "var(--brand-primary)";
  const primaryBg   = "rgba(var(--brand-primary-rgb), 0.12)";
  const primaryText = "var(--brand-sidebar-active)";
  const sidebarText = "var(--brand-sidebar-text)";
  const dimText     = "rgba(var(--brand-primary-rgb), 0.25)";

  // Logo area: if logoUrl provided show img, else show text mark
  const logoInitials = (theme.companyName ?? "HAIP").slice(0, 2).toUpperCase();
  const hasBrightPrimary = brightness(theme.primaryColor) > 160;

  return (
    <aside
      className="w-60 flex flex-col h-full flex-shrink-0"
      style={{
        backgroundColor: sidebarBg,
        borderRight: "1px solid rgba(255,255,255,0.05)",
        fontFamily: "var(--brand-font)",
      }}
    >
      {/* Brand */}
      <Link
        href="/dashboard"
        className="px-5 py-4 flex items-center gap-3 flex-shrink-0 hover:opacity-80 transition-opacity"
        style={{ borderBottom: "1px solid rgba(255,255,255,0.07)" }}
      >
        {theme.logoDarkUrl ? (
          // Custom logo (dark-bg variant)
          <img
            src={theme.logoDarkUrl}
            alt={theme.companyName}
            className="h-8 w-auto object-contain"
          />
        ) : theme.logoUrl ? (
          <img
            src={theme.logoUrl}
            alt={theme.companyName}
            className="h-8 w-auto object-contain"
          />
        ) : (
          <>
            {/* Default text mark with brand primary */}
            <div
              className="w-8 h-8 rounded-lg flex items-center justify-center font-bold text-sm shadow-lg flex-shrink-0"
              style={{
                background: `linear-gradient(135deg, ${theme.primaryColor}, var(--brand-primary-dark))`,
                color: hasBrightPrimary ? "#1a1a1a" : "#ffffff",
                boxShadow: `0 4px 12px rgba(var(--brand-primary-rgb), 0.35)`,
              }}
            >
              {logoInitials}
            </div>
            <div>
              <span
                className="font-bold text-base tracking-tight"
                style={{ color: "#ffffff" }}
              >
                {theme.companyName ?? "HAIP"}
              </span>
              {theme.tagline && (
                <div
                  className="text-[10px] uppercase tracking-widest leading-none mt-0.5"
                  style={{ color: "rgba(255,255,255,0.35)" }}
                >
                  {theme.tagline}
                </div>
              )}
            </div>
          </>
        )}
      </Link>

      {/* Nav */}
      <nav className="flex-1 overflow-y-auto py-2">
        {navSections.map((section) => {
          const visible = section.items.filter(item => canSeeNav(role, item.resource));
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
                const isActive =
                  pathname === item.href ||
                  (item.href !== "/dashboard" && pathname.startsWith(item.href + "/"));

                return (
                  <Link
                    key={item.href + item.label}
                    href={item.href}
                    className={cn(
                      "flex items-center gap-2.5 px-2.5 py-1.5 rounded-md text-sm font-medium transition-all duration-100 mb-0.5 group"
                    )}
                    style={{
                      backgroundColor: isActive ? primaryBg : "transparent",
                      color: isActive ? "#ffffff" : sidebarText,
                      borderRadius: "var(--brand-radius-btn)",
                    }}
                    onMouseEnter={e => {
                      if (!isActive) {
                        (e.currentTarget as HTMLElement).style.backgroundColor = "rgba(255,255,255,0.05)";
                        (e.currentTarget as HTMLElement).style.color = "#ffffff";
                      }
                    }}
                    onMouseLeave={e => {
                      if (!isActive) {
                        (e.currentTarget as HTMLElement).style.backgroundColor = "transparent";
                        (e.currentTarget as HTMLElement).style.color = sidebarText;
                      }
                    }}
                  >
                    <span style={{ color: isActive ? primary : "rgba(255,255,255,0.35)" }}>
                      {item.icon}
                    </span>
                    <span className="flex-1">{item.label}</span>
                    {item.badge && (
                      <span
                        className="text-[10px] px-1.5 py-0.5 rounded-full font-semibold"
                        style={{
                          backgroundColor: `rgba(var(--brand-primary-rgb), 0.20)`,
                          color: primary,
                        }}
                      >
                        {item.badge}
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
        className="p-3 flex-shrink-0"
        style={{ borderTop: "1px solid rgba(255,255,255,0.07)" }}
      >
        <div
          className="flex items-center gap-3 px-2 py-2 rounded-lg cursor-pointer group transition-colors"
          style={{ borderRadius: "var(--brand-radius-btn)" }}
          onMouseEnter={e => { (e.currentTarget as HTMLElement).style.backgroundColor = "rgba(255,255,255,0.05)"; }}
          onMouseLeave={e => { (e.currentTarget as HTMLElement).style.backgroundColor = "transparent"; }}
        >
          <div
            className="w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold flex-shrink-0"
            style={{
              backgroundColor: theme.primaryColor,
              color: hasBrightPrimary ? "#1a1a1a" : "#ffffff",
            }}
          >
            {user?.name?.[0]?.toUpperCase() ?? "U"}
          </div>
          <div className="flex-1 min-w-0">
            <div className="text-white text-xs font-semibold truncate">{user?.name ?? "User"}</div>
            <div
              className="text-[10px] capitalize"
              style={{ color: "rgba(255,255,255,0.35)" }}
            >
              {user?.role ?? "concierge"}
            </div>
          </div>
          <button
            onClick={() => signOut({ callbackUrl: "/login" })}
            className="transition-colors"
            style={{ color: "rgba(255,255,255,0.25)" }}
            title="Sign out"
            onMouseEnter={e => { (e.currentTarget as HTMLElement).style.color = "rgba(255,255,255,0.7)"; }}
            onMouseLeave={e => { (e.currentTarget as HTMLElement).style.color = "rgba(255,255,255,0.25)"; }}
          >
            <LogOut size={14} />
          </button>
        </div>
      </div>
    </aside>
  );
}
