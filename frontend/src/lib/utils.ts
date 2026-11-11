import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatDuration(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export function formatPhone(phone: string): string {
  if (!phone) return "";
  const cleaned = phone.replace(/\D/g, "");
  if (cleaned.length === 12 && cleaned.startsWith("91")) {
    return `+91 ${cleaned.slice(2, 7)} ${cleaned.slice(7)}`;
  }
  return phone;
}

export function formatINR(amount: number): string {
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 0,
  }).format(amount);
}

export function timeAgo(dateStr: string | null | undefined): string {
  if (!dateStr) return "—";
  const date = new Date(dateStr);
  if (isNaN(date.getTime())) return "—";
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  if (diffMs < 0) return "just now";
  const diffMin = Math.floor(diffMs / 60000);
  if (diffMin < 1) return "just now";
  if (diffMin < 60) return `${diffMin}m ago`;
  if (diffMin < 1440) return `${Math.floor(diffMin / 60)}h ago`;
  const diffDays = Math.floor(diffMin / 1440);
  if (diffDays < 30) return `${diffDays}d ago`;
  if (diffDays < 365) return `${Math.floor(diffDays / 30)}mo ago`;
  return `${Math.floor(diffDays / 365)}y ago`;
}

export const DISPOSITION_COLORS: Record<string, string> = {
  hot: "bg-[var(--haip-accent-light)] text-[var(--haip-accent-ink)]",
  quoted: "bg-[var(--haip-status-info-bg)] text-[var(--haip-status-info-fg)]",
  booked: "bg-[var(--haip-status-success-bg)] text-[var(--haip-status-success-fg)]",
  lost: "bg-[var(--haip-status-neutral-bg)] text-[var(--haip-fg-muted)]",
  callback: "bg-[var(--haip-status-warning-bg)] text-[var(--haip-status-warning-fg)]",
  no_answer: "bg-[var(--haip-status-neutral-bg)] text-[var(--haip-fg-2)]",
  voicemail: "bg-[var(--haip-status-info-bg)] text-[var(--haip-status-info-fg)]",
};

export const STAGE_COLORS: Record<string, string> = {
  new: "bg-[var(--haip-status-info-bg)] text-[var(--haip-status-info-fg)]",
  responding: "bg-[var(--haip-status-warning-bg)] text-[var(--haip-status-warning-fg)]",
  quoted: "bg-[var(--haip-status-info-bg)] text-[var(--haip-status-info-fg)]",
  site_visit: "bg-[var(--haip-status-warning-bg)] text-[var(--haip-status-warning-fg)]",
  booked: "bg-[var(--haip-status-success-bg)] text-[var(--haip-status-success-fg)]",
  lost: "bg-[var(--haip-status-danger-bg)] text-[var(--haip-status-danger-fg)]",
  ghosted: "bg-[var(--haip-status-neutral-bg)] text-[var(--haip-fg-subtle)]",
};
