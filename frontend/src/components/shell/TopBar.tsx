"use client";
import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { signOut } from "next-auth/react";
import {
  Bell, Search, User,
  Settings, CreditCard, HelpCircle, LogOut,
  ChevronDown, X,
} from "lucide-react";
import { cn } from "@/lib/utils";

// ─── Types ────────────────────────────────────────────────────────────────────

interface TopBarProps {
  user?: {
    name?: string | null;
    email?: string | null;
    role?: string;
    tenantId?: string;
  };
  workspaceName?: string;
}

// ─── Search bar ───────────────────────────────────────────────────────────────

function GlobalSearch() {
  const [query, setQuery] = useState("");
  const [focused, setFocused] = useState(false);
  const router = useRouter();

  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter" && query.trim()) {
      router.push(`/dashboard/guests?q=${encodeURIComponent(query.trim())}`);
      setQuery("");
    }
    if (e.key === "Escape") {
      setQuery("");
      (e.target as HTMLInputElement).blur();
    }
  }

  return (
    <div
      className="flex items-center gap-2 flex-1 max-w-md px-3.5 py-2 rounded-xl transition-all"
      style={{
        background: "#F8FAFC",
        border: focused ? "1px solid #0F766E" : "1px solid #E5E7EB",
        boxShadow: focused ? "0 0 0 3px rgba(15,118,110,0.08)" : "none",
      }}
    >
      <Search size={14} style={{ color: focused ? "#0F766E" : "#9CA3AF", flexShrink: 0 }} />
      <input
        value={query}
        onChange={e => setQuery(e.target.value)}
        onFocus={() => setFocused(true)}
        onBlur={() => setFocused(false)}
        onKeyDown={handleKeyDown}
        placeholder="Search guests, properties, or AI logs..."
        className="flex-1 bg-transparent text-[13px] outline-none placeholder:text-gray-400 min-w-0"
        style={{ color: "#111827" }}
      />
      {query && (
        <button onClick={() => setQuery("")} style={{ color: "#9CA3AF" }}>
          <X size={12} />
        </button>
      )}
    </div>
  );
}

// ─── Notification bell ────────────────────────────────────────────────────────

function NotificationBell() {
  const [open, setOpen] = useState(false);
  const notifications = [
    { id: 1, text: "Priya Sharma sent a WhatsApp message", time: "2m ago", read: false },
    { id: 2, text: "New call from +91 98765 43210 — transcript ready", time: "15m ago", read: false },
    { id: 3, text: "QA score dropped below 70 for Agent Ravi", time: "1h ago", read: true },
  ];
  const unread = notifications.filter(n => !n.read).length;

  return (
    <div className="relative">
      <button
        onClick={() => setOpen(o => !o)}
        className="relative w-9 h-9 flex items-center justify-center rounded-xl transition-colors"
        style={{ color: "#6B7280" }}
        onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = "#F3F4F6"; }}
        onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = "transparent"; }}
      >
        <Bell size={16} />
        {unread > 0 && (
          <span
            className="absolute top-1.5 right-1.5 w-2 h-2 rounded-full"
            style={{ background: "#EF4444" }}
          />
        )}
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-30" onClick={() => setOpen(false)} />
          <div
            className="absolute right-0 top-full mt-2 z-40 w-80 rounded-2xl overflow-hidden shadow-lg"
            style={{ background: "#fff", border: "1px solid #E5E7EB" }}
          >
            <div
              className="flex items-center justify-between px-4 py-3"
              style={{ borderBottom: "1px solid #F3F4F6" }}
            >
              <span className="text-[11px] font-bold uppercase tracking-wider" style={{ color: "#6B7280" }}>
                Notifications
              </span>
              {unread > 0 && (
                <span
                  className="text-[10px] px-2 py-0.5 rounded-full font-bold"
                  style={{ background: "rgba(15,118,110,0.10)", color: "#0F766E" }}
                >
                  {unread} new
                </span>
              )}
            </div>
            {notifications.map(n => (
              <div
                key={n.id}
                className="px-4 py-3 transition-colors"
                style={{
                  borderBottom: "1px solid #F9FAFB",
                  background: !n.read ? "rgba(15,118,110,0.03)" : "transparent",
                }}
                onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = "#F9FAFB"; }}
                onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = !n.read ? "rgba(15,118,110,0.03)" : "transparent"; }}
              >
                <p className="text-[12.5px] leading-relaxed mb-0.5" style={{ color: "#374151" }}>{n.text}</p>
                <p className="text-[11px]" style={{ color: "#9CA3AF" }}>{n.time}</p>
              </div>
            ))}
            <div className="px-4 py-3 text-center">
              <button className="text-[12px] font-semibold transition-colors" style={{ color: "#0F766E" }}>
                Mark all read
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

// ─── User avatar / menu ───────────────────────────────────────────────────────

function UserMenu({ user }: { user?: TopBarProps["user"] }) {
  const [open, setOpen] = useState(false);
  const initials = user?.name?.[0]?.toUpperCase() ?? "U";

  return (
    <div className="relative">
      <button
        onClick={() => setOpen(o => !o)}
        className="flex items-center gap-1.5 rounded-xl px-1.5 py-1 transition-colors"
        onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = "#F3F4F6"; }}
        onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = "transparent"; }}
      >
        <div
          className="w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold text-white"
          style={{ background: "linear-gradient(135deg, #0F766E, #059669)" }}
        >
          {initials}
        </div>
        <ChevronDown size={11} style={{ color: "#9CA3AF" }} />
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-30" onClick={() => setOpen(false)} />
          <div
            className="absolute right-0 top-full mt-2 z-40 w-52 rounded-2xl overflow-hidden shadow-lg"
            style={{ background: "#fff", border: "1px solid #E5E7EB" }}
          >
            <div className="px-4 py-3" style={{ borderBottom: "1px solid #F3F4F6" }}>
              <p className="text-[13px] font-bold truncate" style={{ color: "#111827" }}>
                {user?.name ?? "User"}
              </p>
              <p className="text-[11px] truncate" style={{ color: "#6B7280" }}>{user?.email}</p>
              <span
                className="inline-flex items-center mt-1.5 text-[10px] px-2 py-0.5 rounded-full font-bold capitalize"
                style={{ background: "rgba(15,118,110,0.10)", color: "#0F766E" }}
              >
                {user?.role ?? "member"}
              </span>
            </div>
            <div className="p-1.5">
              {[
                { icon: <User size={13} />,      label: "Profile",       href: "/dashboard/profile" },
                { icon: <Settings size={13} />,  label: "Settings",      href: "/dashboard/settings" },
                { icon: <CreditCard size={13} />, label: "Billing",      href: "/dashboard/billing" },
                { icon: <HelpCircle size={13} />, label: "Help & support", href: "/dashboard/help" },
              ].map(item => (
                <Link
                  key={item.label}
                  href={item.href}
                  onClick={() => setOpen(false)}
                  className="flex items-center gap-2.5 px-3 py-2 text-[12.5px] rounded-xl transition-colors"
                  style={{ color: "#475569" }}
                  onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = "#F9FAFB"; (e.currentTarget as HTMLElement).style.color = "#111827"; }}
                  onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = "transparent"; (e.currentTarget as HTMLElement).style.color = "#475569"; }}
                >
                  <span style={{ color: "#9CA3AF" }}>{item.icon}</span>
                  {item.label}
                </Link>
              ))}
              <div className="h-px my-1" style={{ background: "#F3F4F6" }} />
              <button
                onClick={() => signOut({ callbackUrl: "/login" })}
                className="w-full flex items-center gap-2.5 px-3 py-2 text-[12.5px] rounded-xl transition-colors"
                style={{ color: "#EF4444" }}
                onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = "rgba(239,68,68,0.05)"; }}
                onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = "transparent"; }}
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

// ─── Main TopBar ──────────────────────────────────────────────────────────────

export function TopBar({ user, workspaceName }: TopBarProps) {
  return (
    <div
      className="h-14 flex items-center justify-between px-5 flex-shrink-0 gap-4"
      style={{
        background: "#FFFFFF",
        borderBottom: "1px solid #E5E7EB",
        zIndex: 10,
      }}
    >
      {/* Left: Platform name */}
      <div className="flex items-center gap-3 flex-shrink-0">
        <span
          className="font-semibold text-[14px] hidden sm:block"
          style={{ fontFamily: "var(--font-display), sans-serif", color: "#111827" }}
        >
          {workspaceName ?? "HAIP Platform"}
        </span>
      </div>

      {/* Center: Search */}
      <div className="flex-1 max-w-md mx-4">
        <GlobalSearch />
      </div>

      {/* Right: Actions */}
      <div className="flex items-center gap-2 flex-shrink-0">
        {/* Notification bell */}
        <NotificationBell />

        {/* User avatar */}
        <UserMenu user={user} />
      </div>
    </div>
  );
}
