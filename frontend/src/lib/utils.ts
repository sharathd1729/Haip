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
  hot: "bg-red-100 text-red-700",
  quoted: "bg-blue-100 text-blue-700",
  booked: "bg-green-100 text-green-700",
  lost: "bg-gray-100 text-gray-600",
  callback: "bg-amber-100 text-amber-700",
  no_answer: "bg-slate-100 text-slate-600",
  voicemail: "bg-purple-100 text-purple-700",
};

export const STAGE_COLORS: Record<string, string> = {
  new: "bg-blue-100 text-blue-700",
  responding: "bg-amber-100 text-amber-700",
  quoted: "bg-purple-100 text-purple-700",
  site_visit: "bg-orange-100 text-orange-700",
  booked: "bg-green-100 text-green-700",
  lost: "bg-red-100 text-red-700",
  ghosted: "bg-gray-100 text-gray-500",
};
