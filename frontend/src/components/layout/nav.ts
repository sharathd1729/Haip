"use client";
// The one navigation model for the app shell (Hospitality Hybrid). The desktop top bar, its "More" menu, the phone bottom
// bar and the phone menu all read this, so a page is reachable the same way everywhere. Visibility follows the same rules
// the old sidebar and phone sheet used (role via canSeeNav, onlyRoles, business type, owner-only); they had drifted apart,
// so this merges both lists.
import { useQuery } from "@tanstack/react-query";
import { usePathname } from "next/navigation";
import type { ComponentType } from "react";
import api from "@/lib/api";
import {
  AtSign, BarChart2, Bot, BookmarkIcon, Building2, Calculator, Calendar, CreditCard, FileText, HelpCircle, Home, Inbox, Key,
  LayoutDashboard, Link2, ListChecks, Megaphone, MessageCircle, Palette, Phone, Send, Settings, Shield, Shuffle, Star, Target,
  TrendingUp, UserCircle, Users, Zap,
} from "@/lib/icons";
import { GitBranch, UserCheck } from "lucide-react";
import { BOOKING_READ_ROLES, QUOTE_WRITE_ROLES, REVENUE_READ_ROLES, canSeeNav, type Resource } from "@/lib/permissions";
import { useBusinessType } from "@/components/providers/WorkspaceProvider";
import { useInboxStore } from "@/store/inbox";

export type NavIcon = ComponentType<{ size?: number; className?: string; strokeWidth?: number }>;

export interface NavLink {
  label: string;
  href: string;
  icon: NavIcon;
  resource: Resource;
  hideForBusinessTypes?: string[];
  /** Shown only for these business types (hidden while the type is still unknown). */
  onlyForBusinessTypes?: string[];
  onlyRoles?: string[];
  ownerOnly?: boolean;
}
export interface NavSection { title: string; links: NavLink[] }

export const NAV_SECTIONS: NavSection[] = [
  { title: "Today", links: [
    { label: "My day", href: "/dashboard/my-day", icon: ListChecks, resource: "inbox" },
    { label: "Home", href: "/dashboard", icon: LayoutDashboard, resource: "dashboard" },
  ] },
  { title: "Conversations", links: [
    { label: "Inbox", href: "/dashboard/inbox", icon: Inbox, resource: "inbox" },
    { label: "Calls", href: "/dashboard/calls", icon: Phone, resource: "calls" },
    { label: "My WhatsApp", href: "/dashboard/settings/whatsapp-personal", icon: MessageCircle, resource: "whatsapp_personal" },
    { label: "AI Concierge", href: "/dashboard/inbox?ch=ai", icon: Bot, resource: "inbox", hideForBusinessTypes: ["caravan"] },
    { label: "Channel manager", href: "/dashboard/inbox/channel-manager", icon: Building2, resource: "inbox", hideForBusinessTypes: ["caravan"] },
  ] },
  { title: "Sales", links: [
    { label: "Leads", href: "/dashboard/leads", icon: Target, resource: "guests" },
    { label: "Calendar", href: "/dashboard/portfolio/calendar", icon: Calendar, resource: "properties" },
    { label: "Bookings", href: "/dashboard/bookings", icon: BookmarkIcon, resource: "guests", onlyRoles: BOOKING_READ_ROLES },
    { label: "Targets", href: "/dashboard/targets", icon: TrendingUp, resource: "guests", onlyRoles: REVENUE_READ_ROLES },
    { label: "Properties", href: "/dashboard/properties", icon: Home, resource: "properties", hideForBusinessTypes: ["caravan"] },
    { label: "Rate calculator", href: "/dashboard/calculator", icon: Calculator, resource: "properties", hideForBusinessTypes: ["caravan"] },
    { label: "Quotes", href: "/dashboard/quotes", icon: Calculator, resource: "guests", onlyRoles: QUOTE_WRITE_ROLES, onlyForBusinessTypes: ["caravan"] },
  ] },
  { title: "Messaging", links: [
    { label: "Overview", href: "/dashboard/messaging", icon: Send, resource: "settings" },
    { label: "Templates", href: "/dashboard/messaging/templates", icon: FileText, resource: "templates" },
    { label: "Campaigns", href: "/dashboard/messaging/campaigns", icon: Megaphone, resource: "campaigns" },
    { label: "Subscribers", href: "/dashboard/messaging/subscribers", icon: UserCheck, resource: "subscribers" },
    { label: "Flow builder", href: "/dashboard/messaging/flows", icon: GitBranch, resource: "flows" },
    { label: "Saved replies", href: "/dashboard/settings/saved-replies", icon: BookmarkIcon, resource: "templates" },
  ] },
  { title: "Insights", links: [
    { label: "Reports", href: "/dashboard/reports", icon: BarChart2, resource: "reports" },
    { label: "Impact", href: "/dashboard/impact", icon: TrendingUp, resource: "analytics", onlyRoles: ["owner", "manager"] },
    { label: "Instagram insights", href: "/dashboard/instagram-insights", icon: AtSign, resource: "analytics" },
    { label: "Marketing", href: "/dashboard/marketing", icon: Megaphone, resource: "analytics", onlyRoles: ["owner", "manager", "marketing"] },
    { label: "QA & scores", href: "/dashboard/qa", icon: Star, resource: "qa" },
    { label: "Compliance", href: "/dashboard/compliance", icon: Shield, resource: "compliance" },
  ] },
  { title: "Workspace", links: [
    { label: "Automations", href: "/dashboard/automations", icon: Zap, resource: "settings" },
    { label: "Settings", href: "/dashboard/settings", icon: Settings, resource: "settings" },
    { label: "Integrations", href: "/dashboard/settings/integrations", icon: Link2, resource: "integrations" },
    { label: "Team", href: "/dashboard/settings/team", icon: Users, resource: "users" },
    { label: "Lead assignment", href: "/dashboard/settings/lead-assignment", icon: Shuffle, resource: "settings" },
    { label: "Calendar sync", href: "/dashboard/settings/calendar-sync", icon: Calendar, resource: "settings" },
    { label: "Payments", href: "/dashboard/settings/payments", icon: CreditCard, resource: "settings" },
    { label: "Invoice details", href: "/dashboard/settings/invoices", icon: FileText, resource: "settings", onlyRoles: ["owner", "manager"] },
    { label: "Developers", href: "/dashboard/settings/developers", icon: Key, resource: "settings" },
    { label: "Branding", href: "/dashboard/settings/branding", icon: Palette, resource: "branding" },
    { label: "Billing", href: "/dashboard/billing", icon: CreditCard, resource: "billing" },
  ] },
  { title: "You", links: [
    { label: "Profile", href: "/dashboard/profile", icon: UserCircle, resource: "profile" },
    { label: "Help & support", href: "/dashboard/help", icon: HelpCircle, resource: "help" },
  ] },
];

/** Desktop top-bar tabs, in order. `wide` ones only fit from lg (1024px) up; below that they live in "More". */
export const PRIMARY_TABS: { href: string; wide?: boolean }[] = [
  { href: "/dashboard/my-day" },
  { href: "/dashboard", wide: true },
  { href: "/dashboard/inbox" },
  { href: "/dashboard/leads" },
  { href: "/dashboard/portfolio/calendar" },
  { href: "/dashboard/calls", wide: true },
];

/** Phone bottom bar: four destinations around the raised "Now" button (My day). */
export const PHONE_TABS = ["/dashboard", "/dashboard/inbox", "/dashboard/leads", "/dashboard/portfolio/calendar"];
export const NOW_HREF = "/dashboard/my-day";

export function isVisible(link: NavLink, role: string, businessType: string | null | undefined): boolean {
  return canSeeNav(role, link.resource)
    && (!link.onlyRoles || link.onlyRoles.includes(role))
    && (!businessType || !link.hideForBusinessTypes?.includes(businessType))
    && (!link.onlyForBusinessTypes || (!!businessType && link.onlyForBusinessTypes.includes(businessType)))
    && (!link.ownerOnly || role === "owner");
}

export function linkActive(pathname: string, href: string): boolean {
  const path = href.split("?")[0];
  if (path === "/dashboard") return pathname === "/dashboard";
  return pathname === path || pathname.startsWith(path + "/");
}

/** Everything the shell needs: visible sections, a lookup by href, live badge counts and the active test. */
export function useNav(role: string) {
  const businessType = useBusinessType();
  const pathname = usePathname() ?? "";
  const { conversations } = useInboxStore();
  const canSeeMyDay = canSeeNav(role, "inbox");
  // Same source and query key as My day, so the badge and the list always agree.
  const { data: queue } = useQuery<{ total: number; severity?: { stale?: number } }>({
    queryKey: ["work-queue", ""],
    queryFn: () => api.get("/work-queue").then(r => r.data),
    staleTime: 30_000,
    refetchInterval: 60_000,
    enabled: canSeeMyDay,
  });
  const sections = NAV_SECTIONS
    .map(s => ({ ...s, links: s.links.filter(l => isVisible(l, role, businessType)) }))
    .filter(s => s.links.length > 0);
  const byHref = new Map(sections.flatMap(s => s.links).map(l => [l.href, l]));
  const unread = conversations.filter(c => (c as { unread_count?: number }).unread_count! > 0).length;
  const waiting = Math.max(0, (queue?.total ?? 0) - (queue?.severity?.stale ?? 0));   // not the cold tail
  const badge = (href: string): number => (href === "/dashboard/inbox" ? unread : href === NOW_HREF ? waiting : 0);
  return { sections, byHref, badge, waiting, isActive: (href: string) => linkActive(pathname, href), pathname };
}
