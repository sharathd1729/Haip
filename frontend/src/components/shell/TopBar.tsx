"use client";

import { useState, useCallback } from "react";
import { usePathname } from "next/navigation";
import Link from "next/link";
import { signOut } from "next-auth/react";
import { cn } from "@/lib/utils";
import {
  Bell, ChevronDown, Building2, Check, LogOut,
  Settings, User, CreditCard, HelpCircle, Search,
  Sparkles, ChevronRight, Sun, Moon,
} from "lucide-react";
import { ChangelogModal } from "@/components/dashboard/ChangelogModal";
import { HelpDrawer } from "@/components/dashboard/HelpDrawer";
import { useThemeMode } from "@/hooks/useThemeMode";

// ---------------------------------------------------------------------------
// Breadcrumb from pathname
// ---------------------------------------------------------------------------

const ROUTE_LABELS: Record<string, string> = {
  dashboard: "Dashboard",
  inbox: "Inbox",
  calls: "Calls",
  whatsapp: "WhatsApp",
  inquiries: "Inquiries",
  guests: "Guests",
  properties: "Properties",
  calendar: "Calendar",
  insights: "AI Insights",
  qa: "QA Scores",
  compliance: "Compliance",
  settings: "Settings",
  integrations: "Integrations",
};

function Breadcrumb() {
  const pathname = usePathname();
  const segments = pathname.split("/").filter(Boolean);

  // Build crumbs: skip "dashboard" in label but keep in link
  const crumbs = segments.map((seg, i) => ({
    label: ROUTE_LABELS[seg] ?? seg.charAt(0).toUpperCase() + seg.slice(1),
    href: "/" + segments.slice(0, i + 1).join("/"),
    isLast: i === segments.length - 1,
  }));

  return (
    <nav className="flex items-center gap-1 text-sm">
      {crumbs.map((crumb, i) => (
        <span key={crumb.href} className="flex items-center gap-1">
          {i > 0 && <ChevronRight size={12} className="text-gray-300 dark:text-white/20" />}
          {crumb.isLast ? (
            <span className="font-semibold text-gray-800 dark:text-white/80">{crumb.label}</span>
          ) : (
            <Link href={crumb.href} className="text-gray-400 hover:text-gray-700 dark:text-white/35 dark:hover:text-white/60 transition-colors">
              {crumb.label}
            </Link>
          )}
        </span>
      ))}
    </nav>
  );
}

// ---------------------------------------------------------------------------
// Notification bell
// ---------------------------------------------------------------------------

function NotificationBell() {
  const [open, setOpen] = useState(false);
  const notifications = [
    { id: 1, text: "Priya Sharma sent a WhatsApp message", time: "2m ago", read: false },
    { id: 2, text: "New call from +91 98765 43210 — transcription ready", time: "15m ago", read: false },
    { id: 3, text: "QA score dropped below 70 for Agent Ravi", time: "1h ago", read: true },
  ];
  const unread = notifications.filter(n => !n.read).length;

  return (
    <div className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="relative w-10 h-10 rounded-lg flex items-center justify-center transition-colors min-h-10 min-w-10 text-gray-400 hover:text-gray-700 hover:bg-gray-100 dark:text-white/40 dark:hover:text-white/70 dark:hover:bg-white/5"
      >
        <Bell size={16} />
        {unread > 0 && (
          <span className="absolute top-1 right-1 w-2 h-2 rounded-full" style={{ backgroundColor: "var(--brand-primary)" }} />
        )}
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-30" onClick={() => setOpen(false)} />
          <div className="absolute right-0 top-full mt-2 z-40 w-80 bg-[#0f2744] border border-white/10 rounded-2xl shadow-2xl shadow-black/40 overflow-hidden">
            <div className="flex items-center justify-between px-4 py-3 border-b border-white/6">
              <span className="text-xs font-bold text-white/60 uppercase tracking-wider">Notifications</span>
              {unread > 0 && (
                <span className="text-[10px] bg-teal-500/20 text-teal-400 px-2 py-0.5 rounded-full font-bold">
                  {unread} new
                </span>
              )}
            </div>
            {notifications.map(n => (
              <div
                key={n.id}
                className={cn(
                  "px-4 py-3 border-b border-white/4 last:border-0 transition-colors hover:bg-white/3",
                  !n.read && "bg-teal-500/4"
                )}
              >
                <p className="text-xs text-white/70 leading-relaxed mb-1">{n.text}</p>
                <p className="text-[10px] text-white/25">{n.time}</p>
              </div>
            ))}
            <div className="px-4 py-3 text-center">
              <button className="text-xs text-teal-400 hover:text-teal-300 font-semibold transition-colors">
                Mark all read
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Workspace switcher
// ---------------------------------------------------------------------------

interface TopBarProps {
  user?: { name?: string | null; email?: string | null; role?: string; tenantId?: string };
  workspaceName?: string;
}

function WorkspaceSwitcher({ workspaceName }: { workspaceName?: string }) {
  const [open, setOpen] = useState(false);
  const name = workspaceName || "My Workspace";

  return (
    <div className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-2 px-2.5 py-1.5 rounded-lg transition-all border hover:bg-gray-100 border-gray-200 hover:border-gray-300 dark:hover:bg-white/5 dark:border-white/8 dark:hover:border-white/15"
      >
        <div className="w-5 h-5 rounded-md bg-teal-500/20 flex items-center justify-center">
          <Building2 size={11} className="text-teal-400" />
        </div>
        <span className="text-xs font-semibold text-gray-700 dark:text-white/70 max-w-[120px] truncate">{name}</span>
        <ChevronDown size={11} className="text-gray-400 dark:text-white/30" />
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-30" onClick={() => setOpen(false)} />
          <div className="absolute left-0 top-full mt-2 z-40 w-64 bg-[#0f2744] border border-white/10 rounded-2xl shadow-2xl shadow-black/40 overflow-hidden">
            <div className="px-4 py-3 border-b border-white/6">
              <p className="text-[10px] font-bold text-white/30 uppercase tracking-wider mb-2">Workspaces</p>
              <div className="flex items-center justify-between px-3 py-2 bg-teal-500/10 rounded-xl border border-teal-500/20">
                <div className="flex items-center gap-2">
                  <div className="w-6 h-6 rounded-md bg-teal-500/30 flex items-center justify-center">
                    <Building2 size={11} className="text-teal-400" />
                  </div>
                  <span className="text-sm font-semibold text-white/80 truncate max-w-[130px]">{name}</span>
                </div>
                <Check size={13} className="text-teal-400 flex-shrink-0" />
              </div>
            </div>
            <div className="p-3">
              <Link
                href="/onboarding"
                onClick={() => setOpen(false)}
                className="flex items-center gap-2 px-3 py-2 text-xs text-white/40 hover:text-white/70 hover:bg-white/5 rounded-xl transition-colors"
              >
                <span className="text-base leading-none">+</span> Add workspace
              </Link>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// User menu
// ---------------------------------------------------------------------------

function UserMenu({ user }: { user?: TopBarProps["user"] }) {
  const [open, setOpen] = useState(false);
  const initials = user?.name?.[0]?.toUpperCase() ?? "U";

  return (
    <div className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-2 rounded-lg hover:bg-gray-100 dark:hover:bg-white/5 px-1.5 py-1 transition-colors"
      >
        <div className="w-7 h-7 rounded-full bg-teal-500 flex items-center justify-center text-xs font-bold text-white">
          {initials}
        </div>
        <ChevronDown size={11} className="text-gray-400 dark:text-white/30" />
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-30" onClick={() => setOpen(false)} />
          <div className="absolute right-0 top-full mt-2 z-40 w-52 bg-[#0f2744] border border-white/10 rounded-2xl shadow-2xl shadow-black/40 overflow-hidden">
            {/* User info */}
            <div className="px-4 py-3 border-b border-white/6">
              <p className="text-sm font-bold text-white truncate">{user?.name ?? "User"}</p>
              <p className="text-xs text-white/30 truncate">{user?.email ?? ""}</p>
              <span className="inline-flex items-center gap-1 mt-1.5 text-[10px] bg-teal-500/15 text-teal-400 px-2 py-0.5 rounded-full font-bold capitalize">
                {user?.role ?? "member"}
              </span>
            </div>
            {/* Links */}
            <div className="p-2">
              {[
                { icon: <User size={13} />, label: "Profile", href: "/dashboard/profile" },
                { icon: <Settings size={13} />, label: "Settings", href: "/dashboard/settings" },
                { icon: <CreditCard size={13} />, label: "Billing", href: "/dashboard/billing" },
                { icon: <HelpCircle size={13} />, label: "Help & support", href: "/dashboard/help" },
              ].map(item => (
                <Link
                  key={item.label}
                  href={item.href}
                  onClick={() => setOpen(false)}
                  className="flex items-center gap-2.5 px-3 py-2 text-xs text-white/50 hover:text-white hover:bg-white/5 rounded-xl transition-colors"
                >
                  <span className="text-white/30">{item.icon}</span>
                  {item.label}
                </Link>
              ))}
              <div className="h-px bg-white/6 my-1.5" />
              <button
                onClick={() => signOut({ callbackUrl: "/login" })}
                className="w-full flex items-center gap-2.5 px-3 py-2 text-xs text-red-400 hover:text-red-300 hover:bg-red-500/8 rounded-xl transition-colors"
              >
                <LogOut size={13} />
                Sign out
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main TopBar export
// ---------------------------------------------------------------------------

export function TopBar({ user, workspaceName }: TopBarProps) {
  const { mode, toggle } = useThemeMode();
  const isDark = mode === "dark";

  return (
    <div
      className={cn(
        "h-12 flex items-center justify-between px-4 flex-shrink-0 gap-3 transition-colors",
        isDark
          ? "border-b border-white/5"
          : "bg-white border-b border-gray-200"
      )}
      style={{
        backgroundColor: isDark ? "var(--brand-topbar-bg, #0B1F3A)" : undefined,
        fontFamily: "var(--brand-font)",
      }}
    >
      {/* Left: breadcrumb */}
      <div className="flex items-center gap-3 min-w-0">
        <WorkspaceSwitcher workspaceName={workspaceName} />
        <div className="hidden sm:block">
          <Breadcrumb />
        </div>
      </div>

      {/* Right: actions */}
      <div className="flex items-center gap-1 flex-shrink-0">
        {/* AI indicator */}
        <div
          className="hidden md:flex items-center gap-1.5 mr-2 rounded-lg px-2.5 py-1"
          style={{
            backgroundColor: "rgba(var(--brand-primary-rgb, 20,184,166), 0.08)",
            border: "1px solid rgba(var(--brand-primary-rgb, 20,184,166), 0.15)",
          }}
        >
          <Sparkles size={10} style={{ color: "var(--brand-primary)" }} />
          <span className="text-[10px] font-semibold" style={{ color: "var(--brand-primary)" }}>AI active</span>
        </div>

        {/* Cmd+K hint (desktop only) */}
        <button
          onClick={() => {
            const isMac = navigator.platform.toUpperCase().includes("MAC");
            window.dispatchEvent(
              new KeyboardEvent("keydown", { key: "k", metaKey: isMac, ctrlKey: !isMac, bubbles: true })
            );
          }}
          className={cn(
            "hidden lg:flex items-center gap-1 px-2 py-1 rounded-md text-[10px] transition-colors font-mono",
            isDark
              ? "text-white/25 hover:text-white/50 hover:bg-white/5"
              : "text-gray-400 hover:text-gray-600 hover:bg-gray-100"
          )}
          title="Open command palette"
        >
          <span>⌘K</span>
        </button>

        {/* Dark / Light mode toggle */}
        <button
          onClick={toggle}
          className={cn(
            "w-8 h-8 flex items-center justify-center rounded-lg transition-colors",
            isDark
              ? "text-white/40 hover:text-white/70 hover:bg-white/8"
              : "text-gray-400 hover:text-gray-700 hover:bg-gray-100"
          )}
          title={isDark ? "Switch to light mode" : "Switch to dark mode"}
        >
          {isDark ? <Sun size={15} /> : <Moon size={15} />}
        </button>

        {/* Help drawer (X10) */}
        <HelpDrawer />

        {/* Changelog (X9) */}
        <ChangelogModal />

        <NotificationBell />
        <UserMenu user={user} />
      </div>
    </div>
  );
}
